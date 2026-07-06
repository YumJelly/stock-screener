"""LINE Bot webhook：使用者輸入股票代號 → 回覆籌碼判讀 + AI 分析。

方案 A：收到訊息先以 replyToken 回覆「查詢中…」，再於背景組出完整分析並 push。

此端點必須為公開（protected=False，見 router.py），並以 X-Line-Signature 驗證來源。
"""
from __future__ import annotations

import json
import logging
from datetime import date

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request

from ...database import SessionLocal
from ...services import line_service
from ...services.chip import broker_chart, stock_context, tracking

logger = logging.getLogger(__name__)

router = APIRouter()

_HELP_TEXT = (
    "📈 台股籌碼判讀機器人\n"
    "\n"
    "・直接輸入股票代號（例如 2330 或 3008）\n"
    "  → 回覆最新籌碼判讀 + AI 分析 + 分點 T 型圖，\n"
    "    並自動加入 30 天追蹤。\n"
    "\n"
    "指令：\n"
    "・/help 或 !help － 顯示本說明\n"
    "・!list － 查看目前的追蹤名單\n"
    "・!rm 代號 － 移除某個追蹤（需二次確認，例如 !rm 2330）\n"
)


def _format_tracking_list(db, user_id: str) -> str:
    """組出使用者追蹤名單的文字。"""
    rows = tracking.list_for_user(db, user_id)
    if not rows:
        return (
            "📋 你目前沒有追蹤中的股票。\n"
            "輸入股票代號（例如 2330）即可開始追蹤 30 天。"
        )
    today = date.today()
    lines = [f"📋 追蹤名單（共 {len(rows)} 檔）"]
    for r in rows:
        name = broker_chart._stock_name(db, r.stock_id) or ""
        header = f"{r.stock_id} {name}".strip()
        # 剩餘天數
        remain = ""
        try:
            exp = date.fromisoformat(r.expires_at)
            remain = f"，剩 {max((exp - today).days, 0)} 天"
        except (ValueError, TypeError):
            pass
        days = broker_chart.count_snapshot_days(db, r.stock_id)
        score = (
            f"，累計分 {r.last_pushed_score:+.2f}"
            if r.last_pushed_score is not None
            else ""
        )
        lines.append(f"・{header}（{days} 日資料{remain}{score}）")
    return "\n".join(lines)



def _push_charts(db, user_id: str, code: str) -> None:
    """若有分點 snapshot，推播單日（+ 累計）T 型圖。"""
    try:
        days = broker_chart.count_snapshot_days(db, code)
        if days <= 0:
            return
        daily_url = tracking.public_chart_url(code, "daily")
        if daily_url:
            line_service.push_image(user_id, daily_url)
        # 至少兩日才送累計圖，避免與單日圖重複。
        if days >= 2:
            cumulative_url = tracking.public_chart_url(code, "cumulative")
            if cumulative_url:
                line_service.push_image(user_id, cumulative_url)
    except Exception:  # noqa: BLE001
        logger.exception("LINE push charts failed for %s", code)


def _process_and_push(user_id: str, code: str) -> None:
    """背景工作：組出完整分析並推播（自帶 DB session）。"""
    db = SessionLocal()
    try:
        text = stock_context.build_reply(db, code)
        line_service.push(user_id, text)

        # 登錄 30 天追蹤（帶 userId，供每日主動推播）。
        market = stock_context.detect_market(db, code)
        try:
            tracking.enroll(db, code, market, line_user_id=user_id)
        except Exception:  # noqa: BLE001
            logger.exception("LINE enroll tracking failed for %s", code)

        # 上市（TWSE）自動抓後會有 snapshot → 推播 T 型圖。
        _push_charts(db, user_id, code)
    except Exception as exc:  # noqa: BLE001
        logger.exception("LINE background analysis failed for %s", code)
        line_service.push(user_id, f"查詢 {code} 時發生錯誤，請稍後再試。")
    finally:
        db.close()



@router.post("/line/webhook", summary="LINE Bot webhook")
async def line_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_line_signature: str | None = Header(default=None),
):
    body = await request.body()

    if not line_service.is_configured():
        raise HTTPException(status_code=503, detail="LINE Bot 尚未設定")

    if not line_service.verify_signature(body, x_line_signature):
        raise HTTPException(status_code=403, detail="簽章驗證失敗")

    try:
        payload = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400, detail="無效的請求內容") from exc

    for event in payload.get("events", []):
        if event.get("type") != "message":
            continue
        message = event.get("message", {})
        if message.get("type") != "text":
            continue

        reply_token = event.get("replyToken")
        user_id = (event.get("source") or {}).get("userId")
        text = message.get("text", "")

        # ── 指令處理 ──────────────────────────────────────────────
        cmd = (text or "").strip().lower()
        if cmd in ("/help", "!help", "help", "?", "？"):
            if reply_token:
                line_service.reply(reply_token, _HELP_TEXT)
            continue
        if cmd in ("!list", "/list", "list"):
            if reply_token:
                db = SessionLocal()
                try:
                    reply_text = _format_tracking_list(db, user_id)
                finally:
                    db.close()
                line_service.reply(reply_token, reply_text)
            continue
        if cmd.startswith(("!rm", "/rm", "rm ")):
            parts = text.strip().split()
            target = (
                stock_context.extract_stock_code(parts[1])
                if len(parts) > 1
                else None
            )
            confirm = len(parts) > 2 and parts[2].strip().lower() in (
                "confirm",
                "yes",
                "y",
                "確認",
            )
            if reply_token:
                if not target:
                    line_service.reply(
                        reply_token, "用法：!rm 代號（例如 !rm 2330）"
                    )
                elif not user_id:
                    line_service.reply(reply_token, "無法辨識使用者，請稍後再試。")
                else:
                    code0 = tracking.bare_code(target)
                    db = SessionLocal()
                    try:
                        tracked = any(
                            r.stock_id == code0
                            for r in tracking.list_for_user(db, user_id)
                        )
                        if not tracked:
                            line_service.reply(
                                reply_token, f"你目前沒有在追蹤 {code0}。"
                            )
                        elif not confirm:
                            # 第一步：要求二次確認（無狀態，確認指令自帶代號）。
                            line_service.reply(
                                reply_token,
                                f"⚠️ 確認要移除 {code0} 的追蹤嗎？\n"
                                f"請回覆：!rm {code0} confirm",
                            )
                        else:
                            # 第二步：已帶 confirm → 實際移除。
                            removed = tracking.remove_for_user(
                                db, target, user_id
                            )
                            line_service.reply(
                                reply_token,
                                f"🗑️ 已移除 {code0} 的追蹤。"
                                if removed
                                else f"你目前沒有在追蹤 {code0}。",
                            )
                    finally:
                        db.close()
            continue

        code = stock_context.extract_stock_code(text)
        if not code:
            if reply_token:
                line_service.reply(reply_token, _HELP_TEXT)
            continue

        if reply_token:
            line_service.reply(reply_token, f"🔎 查詢 {code} 中，請稍候…")
        if user_id:
            background_tasks.add_task(_process_and_push, user_id, code)

    return {"status": "ok"}

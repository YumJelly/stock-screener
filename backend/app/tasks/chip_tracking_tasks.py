"""Chip 30 天追蹤每日任務。

每個台股交易日收盤後執行：
1. 撈出 active 且 market=TWSE 的追蹤股。
2. 以 BSRBlockTradesService（OCR）自動抓當日分點 → 跑判讀 pipeline
   （順帶 upsert ``chip_broker_snapshot``）。
3. 主動推播「累計 T 型圖」給每位訂閱的 LINE user。
4. 累計籌碼分數相對上次推播出現顯著變化（|Δ| >= chip_score_alert_delta，
   或正負轉向）時，額外推播一則文字警示。
5. 過期（expires_at < 今日）→ active=False。

上櫃（TPEX）不自動抓，靠使用者自行上傳 CSV 累積 snapshot。
"""
from __future__ import annotations

import logging
from datetime import date

from ..celery_app import celery_app
from ..config import settings
from ..database import SessionLocal
from ..models.chip_result import ChipDailyResult
from ..models.chip_tracking import ChipTracking
from ..services import line_service
from ..services.chip import broker_chart, pipeline, tracking

logger = logging.getLogger(__name__)


def _latest_cumulative_score(db, stock_id: str, window_days: int) -> float | None:
    """近 ``window_days`` 日判讀分數的平均，作為「累計分數」代理值。"""
    rows = (
        db.query(ChipDailyResult.score)
        .filter(ChipDailyResult.stock_id == stock_id)
        .order_by(ChipDailyResult.trade_date.desc())
        .limit(window_days)
        .all()
    )
    scores = [r[0] for r in rows if r[0] is not None]
    if not scores:
        return None
    return sum(scores) / len(scores)


def _is_significant_change(prev: float | None, curr: float | None) -> bool:
    if curr is None:
        return False
    if prev is None:
        return False  # 首次不視為「變化」（推圖但不推警示）
    if abs(curr - prev) >= settings.chip_score_alert_delta:
        return True
    # 正負轉向（多↔空）也算顯著。
    return (prev > 0 > curr) or (prev < 0 < curr)


def _alert_text(stock_id: str, prev: float, curr: float) -> str:
    direction = "轉強偏多" if curr > prev else "轉弱偏空"
    if prev > 0 >= curr:
        direction = "由多轉空"
    elif prev < 0 <= curr:
        direction = "由空轉多"
    return (
        f"⚠️ {stock_id} 累計籌碼{direction}"
        f"（{prev:+.2f} → {curr:+.2f}，Δ{curr - prev:+.2f}）"
    )


def _fetch_and_process_twse(db, stock_id: str) -> bool:
    """抓 TWSE 分點並跑判讀（含 snapshot 持久化）。成功回 True。"""
    from ..services.bsr_block_trades_service import (
        BlockTradesCaptchaRequired,
        BSRBlockTradesService,
    )

    try:
        svc = BSRBlockTradesService()
        details = svc.fetch_single_stock(stock_id)
    except BlockTradesCaptchaRequired as exc:
        logger.info("chip tracking CAPTCHA failed for %s: %s", stock_id, exc)
        return False
    except Exception as exc:  # noqa: BLE001
        logger.warning("chip tracking fetch failed for %s: %s", stock_id, exc)
        return False

    rows: list = []
    for d in details:
        rows.extend(d.rows)
    if not rows:
        logger.info("chip tracking: no rows for %s today", stock_id)
        return False

    try:
        pipeline.process_rows(db, stock_id, "TWSE", rows, source="twse_ocr")
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("chip tracking process failed for %s: %s", stock_id, exc)
        return False


def _push_updates(db, row: ChipTracking) -> None:
    """推播累計圖 + 顯著變化警示，並更新 last_pushed_score。"""
    user_ids = [u for u in (row.line_user_ids or []) if u]
    curr_score = _latest_cumulative_score(
        db, row.stock_id, settings.chip_tracking_days
    )

    if user_ids:
        cumulative_url = tracking.public_chart_url(row.stock_id, "cumulative")
        if cumulative_url:
            for uid in user_ids:
                line_service.push_image(uid, cumulative_url)
        else:
            logger.info(
                "chip tracking: public_base_url 未設定，略過推圖 %s", row.stock_id
            )

        if _is_significant_change(row.last_pushed_score, curr_score):
            text = _alert_text(row.stock_id, row.last_pushed_score, curr_score)
            for uid in user_ids:
                line_service.push(uid, text)

    if curr_score is not None:
        row.last_pushed_score = curr_score


@celery_app.task(name="app.tasks.chip_tracking_tasks.run_daily_chip_tracking")
def run_daily_chip_tracking() -> dict:
    """每日追蹤：抓分點 → 重繪累計 → 主動推播 → 過期關閉。"""
    db = SessionLocal()
    today = date.today().isoformat()
    processed = 0
    pushed = 0
    expired = 0
    try:
        rows = (
            db.query(ChipTracking)
            .filter(ChipTracking.active.is_(True))
            .all()
        )
        for row in rows:
            # 過期關閉。
            if row.expires_at and row.expires_at < today:
                row.active = False
                expired += 1
                continue

            # 僅自動抓 TWSE；TPEX 靠手動上傳（若今日有新上傳 snapshot 仍會推圖）。
            if (row.market or "TWSE").upper() == "TWSE":
                if _fetch_and_process_twse(db, row.stock_id):
                    processed += 1

            # 有任何 snapshot 才推播。
            if broker_chart.count_snapshot_days(db, row.stock_id) > 0:
                _push_updates(db, row)
                pushed += 1

            db.commit()

        db.commit()
    except Exception:  # noqa: BLE001
        logger.exception("run_daily_chip_tracking failed")
        db.rollback()
    finally:
        db.close()

    result = {
        "processed": processed,
        "pushed": pushed,
        "expired": expired,
    }
    logger.info("run_daily_chip_tracking done: %s", result)
    return result

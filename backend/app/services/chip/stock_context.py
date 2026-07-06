"""LINE Bot 個股查詢：解析代號 → 匯集網站資料 + 最新籌碼判讀 → Ollama 分析。

流程對應「方案 A」：webhook 先回覆「查詢中…」，本模組於背景組出完整回覆文字，
再由 line_service.push() 推播給使用者。
"""
from __future__ import annotations

import logging
import re

from sqlalchemy.orm import Session

from ...models.chip_result import ChipDailyResult
from ...models.stock import StockFundamental, StockPrice, StockTechnical
from ...models.stock_universe import StockUniverse
from . import pipeline

logger = logging.getLogger(__name__)

_TPEX_BROKER_URL = (
    "https://www.tpex.org.tw/zh-tw/mainboard/trading/info/brokerBS.html"
)

_CLASS_NAMES = {
    "1": "低檔殺盤",
    "2": "高檔出貨",
    "3": "平盤交戰",
    "4": "低檔吃貨",
    "5": "高檔追進",
    "6": "高買低賣",
    "7": "高賣低買",
    "8": "低買高賣",
}


def extract_stock_code(text: str) -> str | None:
    """從使用者訊息取出台股代號（4-6 碼數字，可含一位英數）。"""
    if not text:
        return None
    m = re.search(r"\b(\d{4,6}[A-Za-z]?)\b", text.strip())
    return m.group(1).upper() if m else None


def _resolve_symbol(db: Session, code: str) -> str | None:
    """把純代號解析為資料庫中的實際 symbol（2330.TW / 3008.TWO）。"""
    candidates = [code, f"{code}.TW", f"{code}.TWO"]
    for cand in candidates:
        hit = (
            db.query(StockPrice.symbol)
            .filter(StockPrice.symbol == cand)
            .first()
        )
        if hit:
            return hit[0]
    like = (
        db.query(StockPrice.symbol)
        .filter(StockPrice.symbol.like(f"{code}.%"))
        .first()
    )
    return like[0] if like else None


def detect_market(db: Session, code: str) -> str:
    """依 DB 內 symbol 後綴判斷市場（.TWO → TPEX，其餘 → TWSE）。"""
    symbol = _resolve_symbol(db, code)
    if symbol and symbol.upper().endswith(".TWO"):
        return "TPEX"
    return "TWSE"



def _latest_chip(db: Session, code: str) -> ChipDailyResult | None:
    return pipeline.latest_result(db, code)


def _latest_price_date(db: Session, symbol: str | None) -> str | None:
    """該股最新一筆快取股價日期（作為「最近交易日」新鮮度基準）。"""
    if not symbol:
        return None
    row = (
        db.query(StockPrice.date)
        .filter(StockPrice.symbol == symbol)
        .order_by(StockPrice.date.desc())
        .first()
    )
    return str(row[0]) if row else None


def ensure_chip_result(db: Session, code: str) -> str | None:
    """確保該股有「最近交易日」的籌碼判讀；必要時即時驅動 pipeline。

    - TWSE（``.TW``）：以既有 OCR 服務自動抓分點 → 判讀 → 寫入 DB。
    - TPEX（``.TWO``）：官網有 Cloudflare + 每檔非機器人驗證，無法自動抓，
      回傳一段引導訊息請使用者下載 CSV 上傳。

    Returns
    -------
    str | None
        需要附加到回覆的提示訊息（TPEX 引導）；無則 ``None``。
    """
    symbol = _resolve_symbol(db, code)

    # 新鮮度閘門：已有「最近交易日」判讀就不重跑，避免每則訊息都打 CAPTCHA。
    latest = _latest_chip(db, code)
    price_date = _latest_price_date(db, symbol)
    if latest and price_date and latest.trade_date == price_date:
        return None

    # 上櫃：官網 Cloudflare Turnstile 於真實瀏覽器隱形通過，用 Playwright 自動抓分點。
    if symbol and symbol.upper().endswith(".TWO"):
        try:
            from .tpex_broker_service import (
                TPEXBrokerUnavailable,
                fetch_broker_rows,
            )

            rows = fetch_broker_rows(code)
            pipeline.process_rows(db, code, "TPEX", rows)
            return None
        except TPEXBrokerUnavailable as exc:
            logger.info("TPEX auto chip fetch unavailable for %s: %s", code, exc)
        except Exception as exc:  # noqa: BLE001
            logger.warning("TPEX auto chip analysis failed for %s: %s", code, exc)
        # 自動抓取失敗 → Tier 1 引導（已有舊判讀則照舊顯示）。
        if latest:
            return None
        return (
            f"📊 籌碼判讀：{code} 為上櫃（TPEX）股票，自動判讀暫時無法取得。\n"
            f"請至 {_TPEX_BROKER_URL} 下載該股「分點 CSV」，\n"
            "再到本站『籌碼判讀』頁上傳即可產生判讀結果。"
        )

    # 上市（或未解析出市場，預設當 TWSE 嘗試）：自動抓分點判讀。
    try:
        from ...services.bsr_block_trades_service import (
            BlockTradesCaptchaRequired,
            BSRBlockTradesService,
        )

        svc = BSRBlockTradesService()
        details = svc.fetch_single_stock(code)
        rows: list = []
        for d in details:
            rows.extend(d.rows)
        if rows:
            pipeline.process_rows(db, code, "TWSE", rows)
    except BlockTradesCaptchaRequired as exc:
        logger.info("LINE auto chip fetch CAPTCHA failed for %s: %s", code, exc)
    except Exception as exc:  # noqa: BLE001
        logger.warning("LINE auto chip analysis failed for %s: %s", code, exc)
    return None


def _gather_context(db: Session, code: str) -> dict:
    """匯集網站現有資料 + 最新籌碼判讀，回傳緊湊 dict。"""
    ctx: dict = {"code": code}

    symbol = _resolve_symbol(db, code)
    ctx["symbol"] = symbol

    if symbol:
        uni = (
            db.query(StockUniverse.name)
            .filter(StockUniverse.symbol == symbol)
            .first()
        )
        if uni and uni[0]:
            ctx["name"] = uni[0]
        price = (
            db.query(StockPrice)
            .filter(StockPrice.symbol == symbol)
            .order_by(StockPrice.date.desc())
            .first()
        )
        if price:
            ctx["price"] = {
                "date": str(price.date),
                "close": price.close,
                "high": price.high,
                "low": price.low,
                "volume": price.volume,
            }
        tech = (
            db.query(StockTechnical)
            .filter(StockTechnical.symbol == symbol)
            .first()
        )
        if tech:
            ctx["technical"] = {
                "rs_rating": tech.rs_rating,
                "ma_50": tech.ma_50,
                "ma_150": tech.ma_150,
                "ma_200": tech.ma_200,
                "stage": tech.stage,
                "high_52w": tech.high_52w,
                "low_52w": tech.low_52w,
            }
        fund = (
            db.query(StockFundamental)
            .filter(StockFundamental.symbol == symbol)
            .first()
        )
        if fund:
            ctx["fundamental"] = {
                "market_cap": fund.market_cap,
                "pe_ratio": fund.pe_ratio,
                "eps_growth_quarterly": fund.eps_growth_quarterly,
                "eps_growth_annual": fund.eps_growth_annual,
                "revenue_growth": fund.revenue_growth,
            }

    chip = _latest_chip(db, code)
    if chip:
        top = sorted(
            (chip.probabilities or {}).items(), key=lambda kv: -kv[1]
        )[:3]
        ctx["chip"] = {
            "trade_date": chip.trade_date,
            "score": chip.score,
            "summary": chip.summary,
            "top_classes": [
                {"name": _CLASS_NAMES.get(k, k), "prob": v}
                for k, v in top
                if v >= 0.05
            ],
        }
    return ctx


def _format_chip_block(chip: dict | None) -> list[str]:
    if not chip:
        return ["📊 籌碼判讀：尚無資料（請先上傳該股分點 CSV 或執行自動判讀）"]
    lines = [
        f"📊 籌碼判讀（{chip['trade_date']}）",
        f"當日總分：{chip['score']:+.2f}（+2 極多 ~ -2 極空）",
    ]
    for c in chip.get("top_classes", []):
        lines.append(f"・{c['name']} {c['prob']:.0%}")
    if chip.get("summary"):
        lines.append(chip["summary"])
    return lines


def build_reply(db: Session, code: str) -> str:
    """組出要 push 給使用者的完整回覆文字。"""
    # 收到代號先驅動 tracker 判讀（TWSE 自動抓；TPEX 回引導訊息）。
    tpex_hint = ensure_chip_result(db, code)

    ctx = _gather_context(db, code)

    name = ctx.get("name")
    header = f"\U0001f50e {code} {name} 分析" if name else f"\U0001f50e {code} 分析"
    chip_lines = (
        [tpex_hint] if (tpex_hint and not ctx.get("chip")) else _format_chip_block(ctx.get("chip"))
    )

    price = ctx.get("price")
    price_line = (
        f"💹 收盤 {price['close']}（{price['date']}）"
        if price
        else "💹 股價：查無網站快取資料"
    )

    parts = [header, price_line, ""] + chip_lines
    return "\n".join(parts)

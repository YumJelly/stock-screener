"""Chip (籌碼) analysis API endpoints.

POST /v1/chip/analyze              — 上傳分點 CSV（TPEX/TWSE、UTF-8/Big5），同步判讀
POST /v1/chip/analyze-auto/{symbol}— TWSE 走 OCR 自動抓分點後判讀（TPEX 請改用上傳）
GET  /v1/chip/history/{stock_id}   — 歷史分數曲線
GET  /v1/chip/result/{stock_id}/{trade_date} — 單日判讀明細
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from ...database import get_db
from ...models.chip_result import ChipDailyResult
from ...models.stock import StockPrice
from ...services.bsr_block_trades_service import (
    BlockTradesCaptchaRequired,
    BSRBlockTradesService,
)
from ...services.chip import pipeline

logger = logging.getLogger(__name__)

router = APIRouter()


def _detect_market(db: Session, code: str) -> str:
    """依 DB 內的 symbol 後綴判斷市場（.TWO → TPEX，其餘 → TWSE）。"""
    row = (
        db.query(StockPrice.symbol)
        .filter(StockPrice.symbol.like(f"{code}.%"))
        .first()
    )
    if row and str(row[0]).upper().endswith(".TWO"):
        return "TPEX"
    return "TWSE"


def _serialize(row: ChipDailyResult) -> dict:
    return {
        "stock_id": row.stock_id,
        "trade_date": row.trade_date,
        "market": row.market,
        "score": row.score,
        "probabilities": row.probabilities,
        "intensity": row.intensity,
        "summary": row.summary,
        "features": row.features,
    }


def _optional_ohlc(
    open_: float | None,
    high: float | None,
    low: float | None,
    close: float | None,
) -> dict | None:
    if None in (open_, high, low, close):
        return None
    return {"open": open_, "high": high, "low": low, "close": close}


@router.post("/chip/analyze", summary="上傳分點 CSV 判讀")
async def analyze_csv(
    file: UploadFile = File(...),
    market: str | None = Form(default=None),
    open_price: float | None = Form(default=None),
    high_price: float | None = Form(default=None),
    low_price: float | None = Form(default=None),
    close_price: float | None = Form(default=None),
    prev_close: float | None = Form(default=None),
    db: Session = Depends(get_db),
):
    """同步跑完整籌碼判讀並寫入 DB。

    ``market`` 選填（TWSE/TPEX），不填則依 CSV 內容自動判別。
    OHLC 選填，全部提供時以手動值取代 OpenAPI 自動抓取。
    """
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="上傳檔案為空")

    manual_ohlc = _optional_ohlc(open_price, high_price, low_price, close_price)
    try:
        result = pipeline.process_csv(
            db,
            raw,
            file.filename or "",
            market_override=market,
            manual_ohlc=manual_ohlc,
            manual_prev_close=prev_close,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("chip analyze failed")
        raise HTTPException(status_code=500, detail=f"判讀失敗：{exc}") from exc
    return result


@router.post("/chip/analyze-auto/{symbol}", summary="自動抓分點判讀（上市 OCR／上櫃 Playwright）")
def analyze_auto(
    symbol: str,
    market: str | None = None,
    db: Session = Depends(get_db),
):
    """自動抓取分點明細後判讀並寫入 DB。

    - 上市（TWSE）：用 BSR OCR 服務自動抓分點。
    - 上櫃（TPEX）：用 Playwright 通過 Cloudflare Turnstile 抓 brokerBS JSON。

    ``market`` 選填（``TWSE``/``TPEX``），不填則依 DB 內 symbol 後綴自動判別。
    """
    symbol = symbol.strip().upper()
    market = (market or _detect_market(db, symbol)).upper()

    if market == "TPEX":
        return _analyze_auto_tpex(db, symbol)
    return _analyze_auto_twse(db, symbol)


def _analyze_auto_twse(db: Session, symbol: str):
    svc = BSRBlockTradesService()
    try:
        details = svc.fetch_single_stock(symbol)
    except BlockTradesCaptchaRequired as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "message": (
                    "CAPTCHA OCR 失敗，請安裝 ddddocr/pytesseract，"
                    "或改用 CSV 上傳。"
                ),
                "captcha_required": True,
                "error": str(exc),
            },
        ) from exc

    rows: list = []
    for d in details:
        rows.extend(d.rows)
    if not rows:
        raise HTTPException(
            status_code=404,
            detail=(
                f"查無 {symbol} 的分點明細（可能為上櫃股票或當日無資料）。"
                "上櫃股票請改用 CSV 上傳。"
            ),
        )

    try:
        result = pipeline.process_rows(db, symbol, "TWSE", rows)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("chip analyze-auto (TWSE) failed")
        raise HTTPException(status_code=500, detail=f"判讀失敗：{exc}") from exc
    return result


def _analyze_auto_tpex(db: Session, symbol: str):
    from ...services.chip.tpex_broker_service import (
        TPEXBrokerUnavailable,
        fetch_broker_rows,
    )

    try:
        rows = fetch_broker_rows(symbol)
    except TPEXBrokerUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "message": (
                    "上櫃自動抓取失敗（Cloudflare/Playwright），請改用 CSV 上傳。"
                ),
                "error": str(exc),
            },
        ) from exc

    try:
        result = pipeline.process_rows(db, symbol, "TPEX", rows)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("chip analyze-auto (TPEX) failed")
        raise HTTPException(status_code=500, detail=f"判讀失敗：{exc}") from exc
    return result


@router.get("/chip/tpex-debug/{symbol}", summary="上櫃分點抓取 Debug（Playwright，不判讀）")
def tpex_broker_debug(symbol: str):
    """即時用 Playwright 抓取上櫃分點，回傳原始列供人工核對（不跑 LLM、不寫 DB）。"""
    from ...services.chip.tpex_broker_service import (
        TPEXBrokerUnavailable,
        fetch_broker_rows,
    )

    symbol = symbol.strip().upper()
    try:
        rows = fetch_broker_rows(symbol)
    except TPEXBrokerUnavailable as exc:
        return {
            "symbol": symbol,
            "market": "TPEX",
            "success": False,
            "count": 0,
            "records": [],
            "error": str(exc),
        }

    broker_rows = []
    for i, r in enumerate(rows, 1):
        broker = str(r.get("broker", "")).strip()
        parts = broker.split(" ", 1)
        broker_rows.append(
            {
                "seq": i,
                "broker_code": parts[0],
                "broker_name": parts[1] if len(parts) > 1 else "",
                "price": r.get("price"),
                "buy_volume": r.get("buy_volume"),
                "sell_volume": r.get("sell_volume"),
                "trade_type": "一般",
            }
        )

    return {
        "symbol": symbol,
        "market": "TPEX",
        "success": True,
        "count": len(broker_rows),
        "records": [
            {
                "symbol": symbol,
                "name": "",
                "date": "",
                "high_price": max((r["price"] for r in broker_rows), default=0),
                "low_price": min((r["price"] for r in broker_rows), default=0),
                "trade_count": len(broker_rows),
                "total_value": 0,
                "total_volume": sum(
                    (r["buy_volume"] or 0) + (r["sell_volume"] or 0)
                    for r in broker_rows
                ),
                "broker_rows": broker_rows,
            }
        ],
        "error": None,
    }


@router.get("/chip/history/{stock_id}", summary="歷史分數曲線")
def get_history(stock_id: str, limit: int = 120, db: Session = Depends(get_db)):
    rows = pipeline.history(db, stock_id.strip().upper(), limit=limit)
    return {
        "stock_id": stock_id.strip().upper(),
        "points": [
            {
                "trade_date": r.trade_date,
                "score": r.score,
                "summary": r.summary,
            }
            for r in rows
        ],
    }


@router.get("/chip/result/{stock_id}/{trade_date}", summary="單日判讀明細")
def get_result(stock_id: str, trade_date: str, db: Session = Depends(get_db)):
    row = pipeline.get_result(db, stock_id.strip().upper(), trade_date)
    if row is None:
        raise HTTPException(status_code=404, detail="查無此股票／日期的判讀結果")
    return _serialize(row)


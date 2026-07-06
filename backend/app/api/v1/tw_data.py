"""TW-specific data endpoints (CNYes + TWSE block trades).

GET  /v1/tw/stocks/{symbol}/broker-ratings  — 券商升評記錄
POST /v1/tw/stocks/{symbol}/broker-ratings/refresh — 手動更新指定股票的券商評等
GET  /v1/tw/block-trades          — 今日鉅額交易摘要 (TWSE OpenAPI, 無需驗證碼)
GET  /v1/tw/block-trades/{symbol} — 單股鉅額交易券商明細 (bsr.twse.com.tw, 需 OCR)
GET  /v1/tw/block-trades-debug?symbol=2330 — OCR debug：回傳 CAPTCHA 圖片 + 辨識結果 + 表格（symbol 選填，留空查今日全部）
"""
from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

import requests as _requests

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc
from sqlalchemy.orm import Session

from ...database import get_db
from ...models.stock import TWBrokerRating
from ...services.cnyes_tw_service import CNYesTWService
from ...services.bsr_block_trades_service import BSRBlockTradesService, BlockTradesCaptchaRequired

# Optional Redis caching
try:
    from ...services.redis_pool import get_redis_client
    _REDIS_OK = True
except Exception:
    _REDIS_OK = False

BLOCK_TRADE_CACHE_TTL = 6 * 3600  # 6 hours (data published once per day)
TWSE_BLOCK_URL = "https://www.twse.com.tw/rwd/zh/block/BFIAUU"
TWSE_BLOCK_SUMMARY_URL = "https://openapi.twse.com.tw/v1/block/BFIAUU_d"

logger = logging.getLogger(__name__)

router = APIRouter()


def _upsert_broker_ratings(db: Session, records: list[dict]) -> int:
    """Insert/update broker rating rows; returns count of new rows inserted."""
    inserted = 0
    for rec in records:
        existing = (
            db.query(TWBrokerRating)
            .filter_by(
                symbol=rec["symbol"],
                format_date=rec["format_date"],
                broker=rec["broker"],
            )
            .first()
        )
        if existing is None:
            db.add(
                TWBrokerRating(
                    symbol=rec["symbol"],
                    format_date=rec["format_date"],
                    broker=rec["broker"],
                    rate_kind=rec["rate_kind"],
                    new_rate=rec["new_rate"],
                    target_price=rec["target_price"],
                    fetched_at=datetime.now(timezone.utc),
                )
            )
            inserted += 1
    db.commit()
    return inserted


@router.get(
    "/tw/stocks/{symbol}/broker-ratings",
    summary="券商升評記錄",
    tags=["tw-data"],
)
def get_broker_ratings(
    symbol: str,
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """Return recent broker rating records for a TW stock (most recent first)."""
    rows = (
        db.query(TWBrokerRating)
        .filter(TWBrokerRating.symbol == symbol.upper())
        .order_by(desc(TWBrokerRating.format_date))
        .limit(limit)
        .all()
    )
    return {
        "symbol": symbol.upper(),
        "count": len(rows),
        "records": [
            {
                "format_date": r.format_date,
                "broker": r.broker,
                "rate_kind": r.rate_kind,
                "new_rate": r.new_rate,
                "target_price": r.target_price,
                "fetched_at": r.fetched_at.isoformat() if r.fetched_at else None,
            }
            for r in rows
        ],
    }


@router.post(
    "/tw/stocks/{symbol}/broker-ratings/refresh",
    summary="更新券商評等資料",
    tags=["tw-data"],
)
def refresh_broker_ratings(
    symbol: str,
    lookback_days: int = Query(default=90, ge=1, le=365),
    db: Session = Depends(get_db),
):
    """Fetch latest broker ratings from CNYes and upsert into DB."""
    sym = symbol.upper()
    if not (sym.endswith(".TW") or sym.endswith(".TWO")):
        raise HTTPException(
            status_code=400,
            detail=f"{sym} is not a TW/TWO symbol. CNYes data is only available for Taiwan stocks.",
        )

    svc = CNYesTWService()
    try:
        records = svc.fetch_broker_ratings(sym, lookback_days=lookback_days)
    except Exception as exc:
        logger.error("CNYes broker ratings fetch failed for %s: %s", sym, exc)
        raise HTTPException(status_code=502, detail=f"CNYes API error: {exc}") from exc

    if records is None:
        raise HTTPException(status_code=502, detail="CNYes API returned no data.")

    inserted = _upsert_broker_ratings(db, records)
    return {
        "symbol": sym,
        "fetched": len(records),
        "inserted": inserted,
        "lookback_days": lookback_days,
    }


# ---------------------------------------------------------------------------
# Block Trades endpoints
# ---------------------------------------------------------------------------

def _twse_block_summary(date: str | None = None) -> list[dict]:
    """Fetch per-trade block data from TWSE OpenAPI (no CAPTCHA).

    Returns list of dicts with keys: symbol, name, trade_type, price,
    volume, value.  Aggregates multiple records for the same symbol.
    """
    params: dict[str, Any] = {"response": "json"}
    if date:
        # TWSE expects Taiwan calendar date format YYYYMMDD
        params["date"] = date

    try:
        resp = _requests.get(TWSE_BLOCK_URL, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"TWSE API error: {exc}") from exc

    if data.get("stat") != "OK":
        return []

    fields = data.get("fields", [])
    rows = data.get("data", [])

    # Map field names to indices
    idx = {name: i for i, name in enumerate(fields)}
    sym_i = idx.get("證券號", idx.get("證券代號", 0))
    name_i = idx.get("證券名稱", 1)
    type_i = idx.get("交易別", 2)
    price_i = idx.get("成交價", 3)
    vol_i = idx.get("成交股數", 4)
    val_i = idx.get("成交金額", 5)

    def _num(s: str) -> float:
        return float(re.sub(r"[^\d.]", "", s) or "0")

    trades: list[dict] = []
    for row in rows:
        if not row or row[0] == "總計":
            continue
        trades.append(
            {
                "symbol": row[sym_i] if sym_i < len(row) else "",
                "name": row[name_i] if name_i < len(row) else "",
                "trade_type": row[type_i] if type_i < len(row) else "",
                "price": _num(row[price_i]) if price_i < len(row) else 0,
                "volume": int(_num(row[vol_i])) if vol_i < len(row) else 0,
                "value": int(_num(row[val_i])) if val_i < len(row) else 0,
            }
        )

    # Group by symbol → summary
    summary: dict[str, dict] = {}
    for t in trades:
        sym = t["symbol"]
        if sym not in summary:
            summary[sym] = {
                "symbol": sym,
                "name": t["name"],
                "total_volume": 0,
                "total_value": 0,
                "trades": [],
            }
        summary[sym]["total_volume"] += t["volume"]
        summary[sym]["total_value"] += t["value"]
        summary[sym]["trades"].append(
            {
                "trade_type": t["trade_type"],
                "price": t["price"],
                "volume": t["volume"],
                "value": t["value"],
            }
        )

    return list(summary.values())


@router.get(
    "/tw/block-trades",
    summary="今日鉅額交易摘要",
    tags=["tw-data"],
)
def get_block_trades(
    date: str | None = Query(
        default=None,
        description="日期 YYYYMMDD，不填預設今日",
    ),
):
    """Return today's block trade summary from TWSE OpenAPI.

    No CAPTCHA required.  Per-stock aggregation with per-trade price breakdown.
    """
    cache_key = f"tw:block_trades:{date or 'today'}"

    # Try Redis cache first
    if _REDIS_OK:
        try:
            redis = get_redis_client()
            if redis:
                cached = redis.get(cache_key)
                if cached:
                    return {"source": "cache", "data": json.loads(cached)}
        except Exception:
            pass

    summary = _twse_block_summary(date)

    # Cache result
    if _REDIS_OK:
        try:
            redis = get_redis_client()
            if redis:
                redis.setex(cache_key, BLOCK_TRADE_CACHE_TTL, json.dumps(summary))
        except Exception:
            pass

    return {"source": "twse", "data": summary}


@router.get(
    "/tw/block-trades/{symbol}",
    summary="單股鉅額交易券商明細",
    tags=["tw-data"],
)
def get_block_trades_detail(symbol: str):
    """Return broker-level block trade detail for one symbol.

    Scrapes bsr.twse.com.tw with OCR CAPTCHA solving.
    Requires ddddocr or pytesseract to be installed.

    If OCR is unavailable or all CAPTCHA attempts fail, returns
    HTTP 503 with ``captcha_required: true``.
    """
    cache_key = f"tw:block_trades_detail:{symbol.upper()}"

    if _REDIS_OK:
        try:
            redis = get_redis_client()
            if redis:
                cached = redis.get(cache_key)
                if cached:
                    return {"source": "cache", **json.loads(cached)}
        except Exception:
            pass

    svc = BSRBlockTradesService()
    try:
        details = svc.fetch_single_stock(symbol.upper())
    except BlockTradesCaptchaRequired as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "message": (
                    "CAPTCHA OCR failed – install ddddocr or pytesseract "
                    "to enable broker-level block trade data."
                ),
                "captcha_required": True,
                "error": str(exc),
            },
        ) from exc

    if not details:
        return {"source": "bsr", "symbol": symbol.upper(), "records": []}

    result = {
        "source": "bsr",
        "symbol": symbol.upper(),
        "records": [
            {
                "symbol": d.symbol,
                "name": d.name,
                "date": d.date,
                "high_price": d.high_price,
                "low_price": d.low_price,
                "trade_count": d.trade_count,
                "total_value": d.total_value,
                "total_volume": d.total_volume,
                "broker_rows": [
                    {
                        "seq": r.seq,
                        "broker_code": r.broker_code,
                        "broker_name": r.broker_name,
                        "price": r.price,
                        "buy_volume": r.buy_volume,
                        "sell_volume": r.sell_volume,
                        "trade_type": r.trade_type,
                    }
                    for r in d.rows
                ],
            }
            for d in details
        ],
    }

    if _REDIS_OK:
        try:
            redis = get_redis_client()
            if redis:
                redis.setex(cache_key, BLOCK_TRADE_CACHE_TTL, json.dumps(result))
        except Exception:
            pass

    return result


@router.get(
    "/tw/block-trades-debug",
    summary="鉅額交易 OCR Debug（含 CAPTCHA 圖片 + 辨識結果）",
    tags=["tw-data"],
)
def get_block_trades_ocr_debug(
    symbol: str = Query(default="", description="股票代號，留空查詢今日全部"),
    max_attempts: int = Query(default=8, ge=1, le=20, description="最多嘗試次數（1–20）"),
):
    """Debug endpoint: return CAPTCHA image (base64) + OCR result + parsed table.

    Never cached. Each call hits bsr.twse.com.tw live.
    Leave symbol empty to fetch all block trades for today.
    Useful for verifying OCR is working and inspecting raw broker rows.
    """
    svc = BSRBlockTradesService()
    try:
        debug = svc.fetch_single_stock_with_debug(symbol.strip().upper(), max_attempts=max_attempts)
    except BlockTradesCaptchaRequired as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "message": "CAPTCHA OCR failed – install ddddocr or pytesseract.",
                "captcha_required": True,
                "error": str(exc),
            },
        ) from exc

    records_out = [
        {
            "symbol": d.symbol,
            "name": d.name,
            "date": d.date,
            "high_price": d.high_price,
            "low_price": d.low_price,
            "trade_count": d.trade_count,
            "total_value": d.total_value,
            "total_volume": d.total_volume,
            "broker_rows": [
                {
                    "seq": r.seq,
                    "broker_code": r.broker_code,
                    "broker_name": r.broker_name,
                    "price": r.price,
                    "buy_volume": r.buy_volume,
                    "sell_volume": r.sell_volume,
                    "trade_type": r.trade_type,
                }
                for r in d.rows
            ],
        }
        for d in debug.get("records", [])
    ]

    return {
        "symbol": symbol.strip().upper() or None,
        "ocr_success": debug.get("ocr_success", False),
        "captcha_image_b64": debug.get("captcha_image_b64"),
        "attempts": debug.get("attempts", []),
        "error": debug.get("error"),
        "records": records_out,
    }


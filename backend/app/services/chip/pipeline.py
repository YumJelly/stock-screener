"""Chip 判讀完整流程封裝（CSV 上傳、OCR 自動抓、CLI 共用）。

輸入來源有三種，最終都收斂到 :func:`process_dataframe`：
1. CSV bytes（TPEX/TWSE、UTF-8/Big5）— :func:`process_csv`
2. OCR 自動抓的分點 rows（TWSE via BSRBlockTradesService）— :func:`process_rows`
3. 已解析的 DataFrame — :func:`process_dataframe`

結果寫入 PostgreSQL ``chip_daily_result`` 表（依 (stock_id, trade_date) upsert）。
"""
from __future__ import annotations

import pandas as pd
from sqlalchemy.orm import Session

from ...models.chip_broker_snapshot import ChipBrokerSnapshot
from ...models.chip_result import ChipDailyResult
from . import etl, features, llm, market_data, scoring, zones


def _persist_broker_snapshot(
    db: Session,
    stock_id: str,
    trade_date: str,
    market: str,
    source: str | None,
    raw_df: pd.DataFrame,
) -> None:
    """依 (stock_id, trade_date) upsert 原始分點列（供繪製 T 型圖）。

    ``raw_df`` 為 clean_and_tag 之前的原始 ``[Broker, Price, Buy, Sell]``（單位：張）。
    """
    if raw_df is None or raw_df.empty:
        return
    rows = [
        [
            str(r.Broker).strip(),
            float(r.Price),
            float(r.Buy),
            float(r.Sell),
        ]
        for r in raw_df[["Broker", "Price", "Buy", "Sell"]].itertuples(index=False)
    ]
    snap = (
        db.query(ChipBrokerSnapshot)
        .filter(
            ChipBrokerSnapshot.stock_id == stock_id,
            ChipBrokerSnapshot.trade_date == trade_date,
        )
        .one_or_none()
    )
    if snap is None:
        snap = ChipBrokerSnapshot(stock_id=stock_id, trade_date=trade_date)
        db.add(snap)
    snap.market = market
    snap.source = source
    snap.rows = rows
    db.commit()


def _persist(
    db: Session,
    stock_id: str,
    trade_date: str,
    market: str,
    score: float,
    llm_out: dict,
    feats: dict,
) -> ChipDailyResult:
    """依 (stock_id, trade_date) upsert 一筆判讀結果。"""
    row = (
        db.query(ChipDailyResult)
        .filter(
            ChipDailyResult.stock_id == stock_id,
            ChipDailyResult.trade_date == trade_date,
        )
        .one_or_none()
    )
    if row is None:
        row = ChipDailyResult(stock_id=stock_id, trade_date=trade_date)
        db.add(row)

    row.market = market
    row.score = score
    row.probabilities = llm_out.get("probabilities")
    row.intensity = llm_out.get("intensity")
    row.summary = llm_out.get("summary", "")
    row.features = feats
    row.raw_llm = llm_out
    db.commit()
    db.refresh(row)
    return row


def process_dataframe(
    db: Session,
    df: pd.DataFrame,
    stock_id: str,
    market: str,
    trade_date: str | None = None,
    manual_ohlc: dict | None = None,
    manual_prev_close: float | None = None,
    source: str | None = None,
) -> dict:
    """從已解析的分點 DataFrame 跑完整判讀。

    Parameters
    ----------
    df : pd.DataFrame
        欄位 ``[Broker, Price, Buy, Sell]``（單位：張）。
    """
    if df is None or df.empty:
        raise ValueError("分點資料為空，請確認來源檔案／查詢結果")
    if not stock_id:
        raise ValueError("無法判定股票代號")

    # 保留原始分點列（clean_and_tag 之前）供繪製 T 型圖。
    raw_df = df[["Broker", "Price", "Buy", "Sell"]].copy()

    df, main_brokers, hedged = etl.clean_and_tag(df)
    zone_map = zones.learn_zones(df)

    if manual_ohlc:
        ohlc, prev_close = manual_ohlc, manual_prev_close
    else:
        ohlc, prev_close, api_date = market_data.fetch_ohlc(stock_id, market)
        if ohlc is None:
            raise ValueError(
                "OpenAPI 查不到此股票的 OHLC，請改用手動輸入 OHLC/昨收"
            )
        trade_date = trade_date or api_date

    if not trade_date:
        raise ValueError(
            "無法判定交易日期：請用帶日期的檔名（如 2324_1150612.csv），"
            "或確認 OpenAPI 有回傳日期"
        )

    feats = features.build_features(
        df, main_brokers, zone_map, hedged, ohlc, prev_close
    )
    out = llm.classify(feats)
    mid_net = feats["zone_net_buy"].get("Mid", 0.0)
    score = scoring.daily_score(
        out["probabilities"], out.get("intensity", {}), mid_net
    )

    _persist(db, stock_id, trade_date, market, score, out, feats)
    _persist_broker_snapshot(db, stock_id, trade_date, market, source, raw_df)

    return {
        "stock_id": stock_id,
        "trade_date": trade_date,
        "market": market,
        "score": score,
        "llm": out,
        "features": feats,
    }


def process_csv(
    db: Session,
    raw: bytes,
    filename: str,
    market_override: str | None = None,
    manual_ohlc: dict | None = None,
    manual_prev_close: float | None = None,
) -> dict:
    """從上傳的 CSV bytes 跑完整判讀。"""
    df, market, stock_id, trade_date = etl.load_csv_bytes(
        raw, filename, market_override
    )
    if not stock_id:
        raise ValueError(
            "無法從 CSV 內容或檔名判定股票代號，請確認是官網下載的分點日報表"
        )
    return process_dataframe(
        db, df, stock_id, market, trade_date, manual_ohlc, manual_prev_close,
        source="csv",
    )


def process_rows(
    db: Session,
    stock_id: str,
    market: str,
    rows: list,
    trade_date: str | None = None,
    manual_ohlc: dict | None = None,
    manual_prev_close: float | None = None,
    source: str | None = None,
) -> dict:
    """從 OCR 自動抓取的分點 rows 跑完整判讀（TWSE 自動路徑）。"""
    df = etl.dataframe_from_rows(rows)
    if source is None:
        source = "twse_ocr" if (market or "").upper() == "TWSE" else "tpex"
    return process_dataframe(
        db, df, stock_id, market, trade_date, manual_ohlc, manual_prev_close,
        source=source,
    )


def history(db: Session, stock_id: str, limit: int = 120) -> list[ChipDailyResult]:
    """取回某股票近 ``limit`` 日的判讀結果，依日期升冪。"""
    rows = (
        db.query(ChipDailyResult)
        .filter(ChipDailyResult.stock_id == stock_id)
        .order_by(ChipDailyResult.trade_date.desc())
        .limit(limit)
        .all()
    )
    return rows[::-1]


def get_result(
    db: Session, stock_id: str, trade_date: str
) -> ChipDailyResult | None:
    """取回單日判讀明細。"""
    return (
        db.query(ChipDailyResult)
        .filter(
            ChipDailyResult.stock_id == stock_id,
            ChipDailyResult.trade_date == trade_date,
        )
        .one_or_none()
    )


def latest_result(db: Session, stock_id: str) -> ChipDailyResult | None:
    """取回某股票最新一筆判讀結果（供 LINE Bot 回覆使用）。"""
    return (
        db.query(ChipDailyResult)
        .filter(ChipDailyResult.stock_id == stock_id)
        .order_by(ChipDailyResult.trade_date.desc())
        .first()
    )

"""OHLC / 昨收自動抓取（TWSE / TPEX OpenAPI，免驗證碼）。

分點 CSV 需人工下載或 OCR，但 OHLC 與昨收有正式的 OpenAPI 可全自動。
OpenAPI 僅提供「最近一個交易日」的全市場資料。
"""
from __future__ import annotations

import ssl

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.ssl_ import create_urllib3_context

TWSE_ALL = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
TPEX_ALL = (
    "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"
)


class _LaxStrictAdapter(HTTPAdapter):
    """保留 CA 憑證驗證，僅關閉 OpenSSL 嚴格結構檢查。

    TWSE/TPEX 官方憑證缺少 Subject Key Identifier，較新 Python 的嚴格
    X509 驗證會拒絕。此 adapter 仍驗證 CA 信任鏈，只放寬結構性檢查，
    比 verify=False 安全。
    """

    def init_poolmanager(self, *args, **kwargs):
        ctx = create_urllib3_context()
        ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
        kwargs["ssl_context"] = ctx
        return super().init_poolmanager(*args, **kwargs)


def _session() -> requests.Session:
    s = requests.Session()
    s.mount("https://", _LaxStrictAdapter())
    return s


def _f(x):
    try:
        return float(str(x).replace(",", ""))
    except (ValueError, TypeError):
        return None


def _roc_to_iso(d):
    """民國日期 '1150703' → 西元 '2026-07-03'；無法解析回傳 None。"""
    d = str(d).strip()
    if len(d) >= 7 and d.isdigit():
        return f"{int(d[:-4]) + 1911}-{d[-4:-2]}-{d[-2:]}"
    return None


def fetch_ohlc(stock_id: str, market: str):
    """回傳 (ohlc dict, prev_close, trade_date)；查無資料回傳 (None, None, None)。

    trade_date 取自 OpenAPI 的 Date 欄位（該筆為最近一個交易日）。
    """
    sess = _session()
    if market == "TWSE":
        data = sess.get(TWSE_ALL, timeout=30).json()
        row = next((r for r in data if r.get("Code") == stock_id), None)
        if not row:
            return None, None, None
        o, h, l, c = map(
            _f,
            (
                row["OpeningPrice"],
                row["HighestPrice"],
                row["LowestPrice"],
                row["ClosingPrice"],
            ),
        )
        chg = _f(row.get("Change")) or 0.0
        prev = round(c - chg, 2) if c is not None else None
        return {"open": o, "high": h, "low": l, "close": c}, prev, _roc_to_iso(
            row.get("Date")
        )
    else:  # TPEX
        data = sess.get(TPEX_ALL, timeout=30).json()
        row = next(
            (r for r in data if r.get("SecuritiesCompanyCode") == stock_id),
            None,
        )
        if not row:
            return None, None, None
        o, h, l, c = map(_f, (row["Open"], row["High"], row["Low"], row["Close"]))
        chg = _f(row.get("Change")) or 0.0
        prev = round(c - chg, 2) if c is not None else None
        return {"open": o, "high": h, "low": l, "close": c}, prev, _roc_to_iso(
            row.get("Date")
        )

"""
CNYes Taiwan data service.

Fetches TW-specific data not available from yfinance or Finviz:
  - 月營收 (monthly revenue) via marketinfo.api.cnyes.com
  - ESG 評級 (ESG grade) via ws.api.cnyes.com
  - 券商評等 (broker ratings / upgrades) via marketinfo.api.cnyes.com

Symbol conversion:
  2330.TW  → TWS:2330:STOCK
  3008.TWO → TWS:3008:STOCK
"""
import logging
import time
from datetime import datetime, timezone
from typing import Optional

import requests

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}

_TIMEOUT = 10  # seconds per request
_RATE_INTERVAL = 1.0  # minimum seconds between requests


def _to_cnyes_symbol(symbol: str) -> Optional[str]:
    """Convert yfinance symbol to CNYes TWS format.

    >>> _to_cnyes_symbol("2330.TW")
    'TWS:2330:STOCK'
    >>> _to_cnyes_symbol("3008.TWO")
    'TWS:3008:STOCK'
    >>> _to_cnyes_symbol("AAPL")  # non-TW symbol
    None
    """
    if symbol.endswith(".TW"):
        code = symbol[:-3]
    elif symbol.endswith(".TWO"):
        code = symbol[:-4]
    else:
        return None
    if not code.isdigit():
        return None
    return f"TWS:{code}:STOCK"


class CNYesTWService:
    """Fetch TW-specific data from CNYes public APIs."""

    _REVENUE_URL = (
        "https://marketinfo.api.cnyes.com/mi/api/v1"
        "/{cnyes_symbol}/revenue?year=2"
    )
    _ESG_URL = (
        "https://ws.api.cnyes.com/ws/api/v1/esg/state/{cnyes_symbol}"
    )
    _BROKER_URL = (
        "https://marketinfo.api.cnyes.com/mi/api/v1"
        "/{cnyes_symbol}/foreignRate?from={from_ts}&to={to_ts}"
    )

    def __init__(self) -> None:
        self._last_request_at: float = 0.0

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _rate_wait(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < _RATE_INTERVAL:
            time.sleep(_RATE_INTERVAL - elapsed)

    def _get(self, url: str) -> Optional[dict]:
        self._rate_wait()
        try:
            resp = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT)
            self._last_request_at = time.monotonic()
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.HTTPError as exc:
            logger.warning("CNYes HTTP error %s for %s", exc.response.status_code, url)
            return None
        except requests.exceptions.RequestException as exc:
            logger.warning("CNYes request error for %s: %s", url, exc)
            return None
        except ValueError as exc:
            logger.warning("CNYes JSON parse error for %s: %s", url, exc)
            return None

    # ------------------------------------------------------------------
    # Public fetch methods
    # ------------------------------------------------------------------

    def fetch_monthly_revenue(self, symbol: str) -> Optional[dict]:
        """Return latest monthly revenue data for a TW stock.

        Returns:
            {
                "tw_revenue_monthly_latest": int,   # 千元
                "tw_revenue_monthly_yoy": float,    # YoY %
                "tw_revenue_monthly_mom": float,    # MoM %
                "tw_revenue_monthly_date": str,     # "YYYY-MM"
                "tw_revenue_monthly_updated_at": datetime,
            }
            or None on error / non-TW symbol.
        """
        cnyes_sym = _to_cnyes_symbol(symbol)
        if cnyes_sym is None:
            return None

        url = self._REVENUE_URL.format(cnyes_symbol=cnyes_sym)
        data = self._get(url)
        if not data:
            return None

        try:
            payload = data["data"]
            times: list = payload["time"]
            datasets: dict = payload["datasets"]
            revenues: list = datasets["saleMonth"]
            yoy_list: list = datasets.get("yoy", [])
            if not times or not revenues:
                return None

            # Most recent entry is last
            latest_rev = revenues[-1]
            latest_ts = times[-1]
            # Timestamps are in seconds (not milliseconds)
            latest_dt = datetime.fromtimestamp(latest_ts, tz=timezone.utc)
            month_str = latest_dt.strftime("%Y-%m")

            # YoY % is provided directly by the API
            yoy: Optional[float] = float(round(yoy_list[-1], 2)) if yoy_list else None

            # MoM % calculated from consecutive saleMonth values
            mom: Optional[float] = None
            if len(revenues) >= 2:
                prev_month = revenues[-2]
                if prev_month and prev_month != 0:
                    mom = round((latest_rev - prev_month) / abs(prev_month) * 100, 2)

            return {
                "tw_revenue_monthly_latest": int(latest_rev),
                "tw_revenue_monthly_yoy": yoy,
                "tw_revenue_monthly_mom": mom,
                "tw_revenue_monthly_date": month_str,
                "tw_revenue_monthly_updated_at": datetime.now(timezone.utc),
            }
        except (KeyError, IndexError, TypeError) as exc:
            logger.warning("CNYes revenue parse error for %s: %s", symbol, exc)
            return None

    def fetch_esg_rating(self, symbol: str) -> Optional[dict]:
        """Return ESG grade for a TW stock.

        Returns:
            {
                "tw_esg_grade": str,        # e.g. "AAA", "AA", None
                "tw_esg_updated_at": datetime,
            }
            or None on error / non-TW symbol.
        """
        cnyes_sym = _to_cnyes_symbol(symbol)
        if cnyes_sym is None:
            return None

        url = self._ESG_URL.format(cnyes_symbol=cnyes_sym)
        data = self._get(url)
        if not data:
            return None

        try:
            grade = data.get("data", {}).get("esgGrade")
            return {
                "tw_esg_grade": grade,  # may be None for unrated stocks
                "tw_esg_updated_at": datetime.now(timezone.utc),
            }
        except (KeyError, TypeError) as exc:
            logger.warning("CNYes ESG parse error for %s: %s", symbol, exc)
            return None

    def fetch_broker_ratings(self, symbol: str, lookback_days: int = 90) -> Optional[list[dict]]:
        """Return broker upgrade/downgrade records for a TW stock.

        Args:
            symbol: yfinance symbol, e.g. "2330.TW"
            lookback_days: how many days back to query (default 90)

        Returns:
            List of dicts, each:
            {
                "symbol": str,
                "format_date": str,     # "YYYY/MM/DD"
                "broker": str,
                "rate_kind": str,       # e.g. "買進", "中立", "賣出"
                "new_rate": str,
                "target_price": float | None,
            }
            or None on error / non-TW symbol.
        """
        cnyes_sym = _to_cnyes_symbol(symbol)
        if cnyes_sym is None:
            return None

        now_ts = int(datetime.now(timezone.utc).timestamp())
        from_ts = now_ts - lookback_days * 86400
        url = self._BROKER_URL.format(
            cnyes_symbol=cnyes_sym, from_ts=from_ts, to_ts=now_ts
        )
        data = self._get(url)
        if not data:
            return None

        try:
            status = data.get("statusCode") or data.get("status")
            if status not in (200, "200", None):
                logger.debug("CNYes broker API non-200 for %s: %s", symbol, status)
                return []

            rates: list = data.get("data", {}).get("rates") or []
            results = []
            for r in rates:
                tp_str = r.get("formatTargetPrice") or ""
                try:
                    target_price: Optional[float] = float(tp_str) if tp_str.strip() else None
                except ValueError:
                    target_price = None
                results.append({
                    "symbol": symbol,
                    "format_date": r.get("formatDate"),
                    "broker": r.get("broker"),
                    "rate_kind": r.get("rateKind"),
                    "new_rate": r.get("newRate"),
                    "target_price": target_price,
                })
            return results
        except (KeyError, TypeError) as exc:
            logger.warning("CNYes broker parse error for %s: %s", symbol, exc)
            return None

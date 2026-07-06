"""BSR Block Trades Service.

Fetches 鉅額交易 (block trade) broker-level detail from:
  https://bsr.twse.com.tw/bshtm/bsMenu.aspx

The page requires a 5-char alphanumeric CAPTCHA per query.

Strategy:
  1. GET the page → extract __VIEWSTATE / __VIEWSTATEGENERATOR + CAPTCHA GUID
  2. Download CAPTCHA image → solve with ddddocr (preferred) or pytesseract
  3. POST form with stock code + CAPTCHA answer
  4. Parse the HTML result table
  5. Retry up to MAX_ATTEMPTS times if CAPTCHA fails

Fallback:
  When OCR is unavailable or all retries fail, raise BlockTradesCaptchaRequired
  so callers can fall back to TWSE OpenAPI summary data.
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from io import BytesIO
from typing import Optional

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

BSR_BASE = "https://bsr.twse.com.tw/bshtm"
MAX_ATTEMPTS = 3        # production default
MAX_ATTEMPTS_DEBUG = 8  # debug endpoint default (more retries for human inspection)
RETRY_DELAY = 1.5  # seconds between attempts

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Referer": f"{BSR_BASE}/bsMenu.aspx",
}


class BlockTradesCaptchaRequired(Exception):
    """Raised when CAPTCHA cannot be solved and no broker detail is available."""


@dataclass
class BrokerTradeRow:
    seq: int
    broker_code: str
    broker_name: str
    price: float
    buy_volume: int
    sell_volume: int
    trade_type: str  # 配對 / 逐筆


@dataclass
class StockBlockDetail:
    symbol: str
    name: str
    date: str        # YYYYMMDD
    high_price: float
    low_price: float
    trade_count: int
    total_value: int
    total_volume: int
    rows: list[BrokerTradeRow] = field(default_factory=list)


def _solve_captcha_bytes(image_bytes: bytes) -> Optional[str]:
    """Try to OCR the CAPTCHA image.  Returns 5-char string or None."""
    # Strategy 1: ddddocr (best for simple alphanumeric CAPTCHAs)
    try:
        import ddddocr  # type: ignore
        ocr = ddddocr.DdddOcr(show_ad=False)
        result = ocr.classification(image_bytes)
        cleaned = re.sub(r"[^A-Za-z0-9]", "", result).upper()
        if len(cleaned) >= 3:
            return cleaned[:5]
    except ImportError:
        pass
    except Exception as exc:
        logger.debug("ddddocr failed: %s", exc)

    # Strategy 2: pytesseract
    try:
        from PIL import Image  # type: ignore
        import pytesseract  # type: ignore

        img = Image.open(BytesIO(image_bytes)).convert("L")
        # Simple threshold to remove noise
        img = img.point(lambda x: 0 if x < 140 else 255, "1")
        raw = pytesseract.image_to_string(
            img,
            config="--psm 8 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
        )
        cleaned = re.sub(r"[^A-Za-z0-9]", "", raw).upper()
        if len(cleaned) >= 3:
            return cleaned[:5]
    except ImportError:
        pass
    except Exception as exc:
        logger.debug("pytesseract failed: %s", exc)

    return None


def _parse_int(text: str) -> int:
    return int(re.sub(r"[^\d]", "", text) or "0")


def _parse_float(text: str) -> float:
    return float(re.sub(r"[^0-9.]", "", text) or "0")


def _parse_bsr_csv(csv_text: str) -> list[StockBlockDetail]:
    """Parse the BSR CSV download into StockBlockDetail objects.

    Actual CSV format (Big5, already decoded):
        鉅額交易明細彙整表            ← title, skip
        證券代號,="2308"             ← symbol marker line
        序號,券商,單價,買進股數,賣出股數,交易種類  ← header, skip
        1,1590 元大證券,2211.09,15000,15000,配對
        ...
        [blank line]
        證券代號,="2317"
        ...
    """
    import csv as _csv
    import io

    text = csv_text.lstrip("\ufeff")
    reader = _csv.reader(io.StringIO(text))
    rows = list(reader)

    result: list[StockBlockDetail] = []
    current: StockBlockDetail | None = None
    seq_counter = 0

    for row in rows:
        if not row:
            continue

        first = row[0].strip()

        # Symbol marker: 證券代號,="2330"
        if "代號" in first or first.startswith("\u8b49\u5238") or first.startswith("\u80a1\u7968"):
            # Extract symbol from second column: ="2330" → 2330
            if len(row) >= 2:
                raw_sym = row[1].strip().strip('="').strip('"')
                if raw_sym:
                    current = StockBlockDetail(
                        symbol=raw_sym,
                        name="",
                        date="",
                        high_price=0.0,
                        low_price=0.0,
                        trade_count=0,
                        total_value=0,
                        total_volume=0,
                    )
                    seq_counter = 0
                    result.append(current)
            continue

        # Header row: skip lines where first cell is not a digit
        if not first.isdigit():
            continue

        # Data row
        if current is None:
            continue

        try:
            seq = int(first)
            broker_raw = row[1].strip() if len(row) > 1 else ""
            # broker column: "1590 元大證券" → code="1590", name="元大證券"
            parts = broker_raw.split(" ", 1)
            broker_code = parts[0] if parts else broker_raw
            broker_name = parts[1] if len(parts) > 1 else broker_raw

            price = _parse_float(row[2]) if len(row) > 2 else 0.0
            buy_vol = _parse_int(row[3]) if len(row) > 3 else 0
            sell_vol = _parse_int(row[4]) if len(row) > 4 else 0
            trade_type = row[5].strip() if len(row) > 5 else "配對"

            current.rows.append(BrokerTradeRow(
                seq=seq,
                broker_code=broker_code,
                broker_name=broker_name,
                price=price,
                buy_volume=buy_vol,
                sell_volume=sell_vol,
                trade_type=trade_type,
            ))
            current.trade_count += 1
            current.total_volume += buy_vol + sell_vol
            current.total_value += int(price * (buy_vol + sell_vol))
            if price:
                if current.high_price == 0.0 or price > current.high_price:
                    current.high_price = price
                if current.low_price == 0.0 or price < current.low_price:
                    current.low_price = price
        except Exception:
            continue

    return [d for d in result if d.rows]


def _parse_single_stock_csv(csv_text: str) -> list[StockBlockDetail]:
    """Parse per-stock broker CSV from bsContent.aspx (RadioButton_Normal mode).

    Format (Big5, already decoded):
        券商買賣股票成交價量資訊               ← title, skip
        股票代碼,="2330"                     ← symbol marker
        序號,券商,價格,買進股數,賣出股數,,序號,券商,價格,買進股數,賣出股數  ← header (TWO records per row)
        1,1020合　　庫,2345.00,434,181,,2,1020合　　庫,2350.00,1259,2565
        ...
    Each CSV row contains two broker records side by side (cols 0-4 and cols 6-10).
    Col 5 is always empty (separator).
    """
    import csv as _csv
    import io

    text = csv_text.lstrip("\ufeff")
    reader = _csv.reader(io.StringIO(text))
    rows = list(reader)

    symbol = ""
    broker_rows: list[BrokerTradeRow] = []
    in_data = False

    for row in rows:
        if not row:
            continue
        first = row[0].strip()

        # Symbol marker line: 股票代碼,="2330"
        if "代碼" in first or "代號" in first:
            if len(row) >= 2:
                symbol = row[1].strip().strip('="').strip('"')
            continue

        # Header row: first cell is "序號"
        if first == "序號":
            in_data = True
            continue

        if not in_data:
            continue

        # Data row: may have up to 11 columns (two records)
        def _extract(r: list[str], offset: int) -> Optional[BrokerTradeRow]:
            try:
                seq_cell = r[offset].strip() if offset < len(r) else ""
                if not seq_cell or not seq_cell.isdigit():
                    return None
                broker_raw = r[offset + 1].strip() if offset + 1 < len(r) else ""
                parts = broker_raw.split(" ", 1)
                broker_code = parts[0]
                broker_name = parts[1] if len(parts) > 1 else broker_raw
                price = _parse_float(r[offset + 2]) if offset + 2 < len(r) else 0.0
                buy_vol = _parse_int(r[offset + 3]) if offset + 3 < len(r) else 0
                sell_vol = _parse_int(r[offset + 4]) if offset + 4 < len(r) else 0
                return BrokerTradeRow(
                    seq=int(seq_cell),
                    broker_code=broker_code,
                    broker_name=broker_name,
                    price=price,
                    buy_volume=buy_vol,
                    sell_volume=sell_vol,
                    trade_type="一般",
                )
            except Exception:
                return None

        # First record in columns 0-4
        rec1 = _extract(row, 0)
        if rec1:
            broker_rows.append(rec1)

        # Second record in columns 6-10 (col 5 is separator)
        rec2 = _extract(row, 6)
        if rec2:
            broker_rows.append(rec2)

    if not broker_rows:
        return []

    prices = [r.price for r in broker_rows if r.price]
    detail = StockBlockDetail(
        symbol=symbol,
        name="",
        date="",
        high_price=max(prices) if prices else 0.0,
        low_price=min(prices) if prices else 0.0,
        trade_count=len(broker_rows),
        total_value=int(sum(r.price * (r.buy_volume + r.sell_volume) for r in broker_rows)),
        total_volume=sum(r.buy_volume + r.sell_volume for r in broker_rows),
        rows=broker_rows,
    )
    return [detail]


def _parse_result_html(html: str) -> list[StockBlockDetail]:
    """Parse the BSR result page into StockBlockDetail objects."""
    soup = BeautifulSoup(html, "html.parser")
    results: list[StockBlockDetail] = []

    # Each stock block is a div or table section.
    # Header format: 交易日期 YYYYMMDD  股票代號 XXXX 名稱  最高價 N  最低價 N
    #                成交筆數 N  成交金額 N  成交股數 N
    # Detail rows: 序號 | 證券商 | 成交單價 | 買進股數 | 賣出股數 | 交易種類

    # The page uses nested tables; find all tables that look like stock blocks
    tables = soup.find_all("table")

    current_detail: Optional[StockBlockDetail] = None

    for table in tables:
        rows_el = table.find_all("tr")
        if not rows_el:
            continue

        first_row_text = " ".join(rows_el[0].get_text(" ", strip=True).split())

        # Detect header row containing "交易日期"
        if "交易日期" in first_row_text or "股票代號" in first_row_text:
            # Parse header info from this table
            full_text = " ".join(table.get_text(" ", strip=True).split())

            date_m = re.search(r"交易日期\s*(\d{8})", full_text)
            sym_m = re.search(r"股票代號\s*(\d+)\s*([\u4e00-\u9fff\w*\-\.]+)", full_text)
            high_m = re.search(r"最高價\s*([0-9,\.]+)", full_text)
            low_m = re.search(r"最低價\s*([0-9,\.]+)", full_text)
            count_m = re.search(r"成交筆數\s*([0-9,]+)", full_text)
            value_m = re.search(r"成交金額\s*([0-9,]+)", full_text)
            volume_m = re.search(r"成交股數\s*([0-9,]+)", full_text)

            if sym_m:
                current_detail = StockBlockDetail(
                    symbol=sym_m.group(1),
                    name=sym_m.group(2).strip(),
                    date=date_m.group(1) if date_m else "",
                    high_price=_parse_float(high_m.group(1)) if high_m else 0.0,
                    low_price=_parse_float(low_m.group(1)) if low_m else 0.0,
                    trade_count=_parse_int(count_m.group(1)) if count_m else 0,
                    total_value=_parse_int(value_m.group(1)) if value_m else 0,
                    total_volume=_parse_int(volume_m.group(1)) if volume_m else 0,
                )
                results.append(current_detail)
            continue

        # Detect detail rows: first col is a number (序號)
        if current_detail is None:
            continue

        for tr in rows_el:
            cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
            if len(cells) < 5:
                continue
            if not cells[0].isdigit():
                continue
            try:
                current_detail.rows.append(
                    BrokerTradeRow(
                        seq=int(cells[0]),
                        broker_code=cells[1].split()[0] if cells[1] else "",
                        broker_name=" ".join(cells[1].split()[1:]) if len(cells[1].split()) > 1 else cells[1],
                        price=_parse_float(cells[2]),
                        buy_volume=_parse_int(cells[3]),
                        sell_volume=_parse_int(cells[4]),
                        trade_type=cells[5] if len(cells) > 5 else "配對",
                    )
                )
            except Exception:
                pass

    return results


class BSRBlockTradesService:
    """Service for fetching broker-level block trade detail from bsr.twse.com.tw."""

    def __init__(self, request_delay: float = 0.5):
        self.request_delay = request_delay
        self._session: Optional[requests.Session] = None

    def _get_session(self) -> requests.Session:
        if self._session is None:
            self._session = requests.Session()
            self._session.headers.update(_HEADERS)
        return self._session

    def _fetch_page_meta(self) -> dict:
        """GET main page; extract ViewState, EventValidation, CAPTCHA GUID."""
        sess = self._get_session()
        resp = sess.get(f"{BSR_BASE}/bsMenu.aspx", timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        def _hidden(name: str) -> str:
            el = soup.find("input", {"id": name}) or soup.find("input", {"name": name})
            return el["value"] if el else ""

        vs = _hidden("__VIEWSTATE")
        vsg = _hidden("__VIEWSTATEGENERATOR")
        ev = _hidden("__EVENTVALIDATION")

        captcha_img = soup.find("img", src=re.compile(r"CaptchaImage\.aspx", re.I))
        guid = ""
        if captcha_img:
            src = captcha_img.get("src", "")
            m = re.search(r"guid=([^&\"']+)", src, re.I)
            if m:
                guid = m.group(1)

        # Find submit button name
        btn = (
            soup.find("input", {"name": "btnOK"})
            or soup.find("input", {"type": "submit"})
            or soup.find("input", {"type": "button", "value": "查詢"})
        )
        btn_name = btn.get("name", "btnOK") if btn else "btnOK"

        return {
            "viewstate": vs,
            "viewstategenerator": vsg,
            "eventvalidation": ev,
            "guid": guid,
            "btn_name": btn_name,
        }

    def _download_captcha(self, guid: str) -> bytes:
        sess = self._get_session()
        resp = sess.get(
            f"{BSR_BASE}/CaptchaImage.aspx",
            params={"guid": guid},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.content

    def _post_query(self, symbol: str, captcha_text: str, meta: dict) -> str:
        """POST the search form and return response HTML.

        Mode depends on whether a symbol is provided:
        - symbol provided → RadioButton_Normal (一般交易, per-stock broker detail)
        - symbol empty    → RadioButton_Excd   (鉅額交易, all block trades today)
        """
        sess = self._get_session()
        data = {
            "__VIEWSTATE": meta["viewstate"],
            "__VIEWSTATEGENERATOR": meta["viewstategenerator"],
            "TextBox_Stkno": symbol,
            "CaptchaControl1": captcha_text,
            meta["btn_name"]: "查詢",
        }
        if symbol:
            data["RadioButton_Normal"] = "RadioButton_Normal"
        else:
            data["RadioButton_Excd"] = "RadioButton_Excd"
        if meta["eventvalidation"]:
            data["__EVENTVALIDATION"] = meta["eventvalidation"]

        resp = sess.post(f"{BSR_BASE}/bsMenu.aspx", data=data, timeout=15)
        resp.encoding = resp.apparent_encoding or "utf-8"
        return resp.text

    def _extract_csv_url(self, html: str) -> Optional[str]:
        """Extract the CSV download URL from the result page."""
        soup = BeautifulSoup(html, "html.parser")
        link = soup.find("a", {"id": "HyperLink_DownloadCSV"})
        if not link:
            return None
        href = link.get("href", "")
        if not href:
            return None
        if href.startswith("http"):
            return href
        # relative URL like "bsExcdContent.aspx?..."
        return f"{BSR_BASE}/{href.lstrip('./')}"

    def _fetch_csv(self, csv_url: str) -> str:
        """Download the CSV content from the result URL."""
        sess = self._get_session()
        resp = sess.get(csv_url, timeout=20)
        # BSR CSV is Big5 encoded
        for enc in ("big5", "cp950", resp.apparent_encoding, "utf-8-sig", "utf-8"):
            try:
                if enc:
                    return resp.content.decode(enc)
            except Exception:
                continue
        return resp.text

    def fetch_single_stock(
        self, symbol: str, max_attempts: int = MAX_ATTEMPTS
    ) -> list[StockBlockDetail]:
        """Fetch broker-level block trade detail for one stock.

        Returns a list (usually one entry) of StockBlockDetail.
        Raises BlockTradesCaptchaRequired if CAPTCHA cannot be solved.
        """
        last_error: Optional[Exception] = None

        for attempt in range(1, max_attempts + 1):
            try:
                # Fresh page meta each attempt (new CAPTCHA GUID)
                meta = self._fetch_page_meta()
                if not meta["guid"]:
                    raise BlockTradesCaptchaRequired("Could not extract CAPTCHA GUID from page")

                captcha_img_bytes = self._download_captcha(meta["guid"])
                captcha_text = _solve_captcha_bytes(captcha_img_bytes)

                if not captcha_text:
                    logger.warning("BSR CAPTCHA OCR returned None on attempt %d", attempt)
                    if attempt < max_attempts:
                        time.sleep(RETRY_DELAY)
                    continue

                logger.debug("BSR CAPTCHA attempt %d: OCR=%r", attempt, captcha_text)
                html = self._post_query(symbol, captcha_text, meta)

                # Check for CAPTCHA failure indicators
                if "驗證碼" in html and "不正確" in html:
                    logger.warning("BSR CAPTCHA wrong on attempt %d (OCR=%r)", attempt, captcha_text)
                    if attempt < max_attempts:
                        time.sleep(RETRY_DELAY)
                    continue

                if "查無資料" in html or "無鉅額交易" in html:
                    return []  # No block trades for this stock today

                # Per-stock broker detail lives in the downloadable CSV
                # (bsContent.aspx), not the HTML result page. Prefer the CSV
                # path (same as fetch_single_stock_with_debug); fall back to
                # HTML parsing only if no CSV link is present.
                csv_url = self._extract_csv_url(html)
                if csv_url:
                    csv_text = self._fetch_csv(csv_url)
                    details = (
                        _parse_single_stock_csv(csv_text)
                        if symbol
                        else _parse_bsr_csv(csv_text)
                    )
                    if details:
                        return details

                details = _parse_result_html(html)
                if details:
                    return details

                logger.warning("BSR parse returned empty on attempt %d", attempt)
                if attempt < max_attempts:
                    time.sleep(RETRY_DELAY)

            except BlockTradesCaptchaRequired:
                raise
            except Exception as exc:
                last_error = exc
                logger.warning("BSR fetch attempt %d failed: %s", attempt, exc)
                if attempt < max_attempts:
                    time.sleep(RETRY_DELAY)

        raise BlockTradesCaptchaRequired(
            f"Failed to fetch BSR data for {symbol} after {max_attempts} attempts. "
            f"Last error: {last_error}"
        )

    def fetch_single_stock_with_debug(
        self, symbol: str, max_attempts: int = MAX_ATTEMPTS_DEBUG
    ) -> dict:
        """Like fetch_single_stock but also returns OCR debug info.

        Returns a dict with keys:
          - records: list of StockBlockDetail (same as fetch_single_stock)
          - attempts: list of per-attempt debug dicts
          - captcha_image_b64: base64 PNG of the last CAPTCHA image tried
          - ocr_success: bool
        """
        import base64

        attempts_log: list[dict] = []
        last_captcha_b64: str | None = None
        last_error: Exception | None = None

        for attempt in range(1, max_attempts + 1):
            attempt_entry: dict = {"attempt": attempt}
            try:
                meta = self._fetch_page_meta()
                if not meta["guid"]:
                    attempt_entry["error"] = "Could not extract CAPTCHA GUID"
                    attempts_log.append(attempt_entry)
                    break

                captcha_img_bytes = self._download_captcha(meta["guid"])
                last_captcha_b64 = base64.b64encode(captcha_img_bytes).decode()
                attempt_entry["captcha_image_b64"] = last_captcha_b64

                captcha_text = _solve_captcha_bytes(captcha_img_bytes)
                attempt_entry["ocr_raw"] = captcha_text

                if not captcha_text:
                    attempt_entry["result"] = "ocr_failed"
                    attempts_log.append(attempt_entry)
                    if attempt < max_attempts:
                        time.sleep(RETRY_DELAY)
                    continue

                html = self._post_query(symbol, captcha_text, meta)

                if "驗證碼" in html and "不正確" in html:
                    attempt_entry["result"] = "captcha_wrong"
                    attempts_log.append(attempt_entry)
                    if attempt < max_attempts:
                        time.sleep(RETRY_DELAY)
                    continue

                if "查無資料" in html or "無鉅額交易" in html:
                    attempt_entry["result"] = "no_data"
                    attempts_log.append(attempt_entry)
                    return {
                        "records": [],
                        "attempts": attempts_log,
                        "captcha_image_b64": last_captcha_b64,
                        "ocr_success": True,
                    }

                # Try CSV path first (cleanest data source)
                csv_url = self._extract_csv_url(html)
                if csv_url:
                    attempt_entry["csv_url"] = csv_url
                    csv_text = self._fetch_csv(csv_url)
                    attempt_entry["result"] = "success"
                    attempts_log.append(attempt_entry)
                    # Choose parser based on mode
                    if symbol:
                        details = _parse_single_stock_csv(csv_text)
                    else:
                        details = _parse_bsr_csv(csv_text)
                    return {
                        "records": details,
                        "attempts": attempts_log,
                        "captcha_image_b64": last_captcha_b64,
                        "ocr_success": True,
                        "csv_url": csv_url,
                        "csv_raw": csv_text[:6000],
                    }

                details = _parse_result_html(html)
                if details:
                    attempt_entry["result"] = "success"
                    attempts_log.append(attempt_entry)
                    return {
                        "records": details,
                        "attempts": attempts_log,
                        "captcha_image_b64": last_captcha_b64,
                        "ocr_success": True,
                        "html_snippet": html[:3000],
                    }

                attempt_entry["result"] = "parse_empty"
                # Extract visible text (skips CSS/scripts) for debugging
                try:
                    _soup = BeautifulSoup(html, "html.parser")
                    for tag in _soup(["style", "script"]):
                        tag.decompose()
                    page_text = _soup.get_text(" ", strip=True)
                    attempt_entry["html_snippet"] = page_text[:4000]
                except Exception:
                    attempt_entry["html_snippet"] = html[:3000]
                attempts_log.append(attempt_entry)
                if attempt < max_attempts:
                    time.sleep(RETRY_DELAY)

            except BlockTradesCaptchaRequired:
                raise
            except Exception as exc:
                last_error = exc
                attempt_entry["error"] = str(exc)
                attempt_entry["result"] = "exception"
                attempts_log.append(attempt_entry)
                if attempt < max_attempts:
                    time.sleep(RETRY_DELAY)

        return {
            "records": [],
            "attempts": attempts_log,
            "captcha_image_b64": last_captcha_b64,
            "ocr_success": False,
            "error": str(last_error) if last_error else "All attempts failed",
        }

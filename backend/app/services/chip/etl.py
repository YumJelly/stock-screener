"""Chip pipeline Phase 1: 分點明細 CSV 解析、同價位對沖清洗與主力鎖定。

支援多種台股分點明細格式，並修正 tracker 原始 ``detect_market`` 用「編碼」
判斷市場的 bug（Big5 的 TPEX 檔會被誤判為 TWSE）。改以「內容/表頭」判斷：

- **TPEX 上櫃**：單欄 5 欄格式，官網可下 UTF-8 或 Big5 兩版
  表頭 ``序號,券商,價格,買進股數,賣出股數``，標題 ``券商買賣證券成交價量資訊``。
- **TWSE 上市（bsr 鉅額）**：單欄 6 欄格式
  表頭 ``序號,券商,單價,買進股數,賣出股數,交易種類``。
- **TWSE 舊式雙欄 big5**：每列左（欄 1-4）右（欄 7-10）並排兩組資料。

亦支援由 OCR 自動抓取（``BSRBlockTradesService``）已解析好的 rows，透過
:func:`dataframe_from_rows` 轉為統一 DataFrame。

所有來源最終都正規化為欄位 ``[Broker, Price, Buy, Sell]``（單位：張）。
"""
from __future__ import annotations

import re

import pandas as pd

_COLUMNS = ["Broker", "Price", "Buy", "Sell"]


def _decode(raw: bytes) -> str:
    """以多編碼 fallback 解碼原始 bytes（比照 bsr_block_trades_service）。"""
    for enc in ("utf-8-sig", "big5", "cp950", "utf-8"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="ignore")


def parse_filename(filename: str) -> tuple[str | None, str | None]:
    """解析檔名取得 (股號, 交易日)。

    - ``'2324_1150612.csv'`` → ``('2324', '2026-06-12')``（民國年轉西元）
    - ``'2324.csv'``         → ``('2324', None)``
    - 無法解析股號 → ``(None, None)``
    """
    m = re.match(r"(\d{4,6}[A-Za-z]?)_(\d{3})(\d{2})(\d{2})", filename)
    if m:
        sid = m.group(1)
        year = int(m.group(2)) + 1911
        return sid, f"{year}-{m.group(3)}-{m.group(4)}"
    m2 = re.match(r"(\d{4,6}[A-Za-z]?)(?:\D|$)", filename)
    if m2:
        return m2.group(1), None
    return None, None


def _extract_symbol(lines: list[str]) -> str | None:
    """從 CSV 內的「證券代碼 / 證券代號」行取出股號（比檔名可靠）。"""
    for ln in lines[:6]:
        if "證券代碼" in ln or "證券代號" in ln:
            after = ln.split(",", 1)[1] if "," in ln else ln
            m = re.search(r"(\d{4,6}[A-Za-z]?)", after)
            if m:
                return m.group(1)
    return None


def _split(line: str) -> list[str]:
    return [c.strip().strip('"') for c in line.split(",")]


def detect_market(lines: list[str]) -> tuple[str, str]:
    """以內容判斷 (market, shape)。

    Returns
    -------
    market : str
        ``'TWSE'`` 或 ``'TPEX'``（決定 OHLC OpenAPI 來源）。
    shape : str
        ``'single5'`` / ``'single6'`` / ``'double'``（決定列解析方式）。
    """
    header_blob = "\n".join(lines[:8])
    for ln in lines[:8]:
        cols = _split(ln)
        if "券商" not in cols:
            continue
        if "交易種類" in cols or "單價" in cols:
            return "TWSE", "single6"
        if "價格" in cols:
            return "TPEX", "single5"
    if "鉅額交易明細彙整表" in header_blob:
        return "TWSE", "single6"
    if "券商買賣證券成交價量資訊" in header_blob:
        return "TPEX", "single5"
    # 無法辨識單欄表頭 → 視為 TWSE 舊式 big5 雙欄
    return "TWSE", "double"


def _parse_single(lines: list[str]) -> pd.DataFrame:
    """單欄格式（TPEX 5 欄 / TWSE bsr 6 欄）。

    兩者的欄位索引一致：券商=1、價格/單價=2、買進股數=3、賣出股數=4。
    """
    start: int | None = None
    for i, ln in enumerate(lines):
        if "券商" in _split(ln):
            start = i + 1
            break
    if start is None:
        return pd.DataFrame(columns=_COLUMNS)

    rows: list[list] = []
    for ln in lines[start:]:
        cols = _split(ln)
        if len(cols) < 5:
            continue
        broker = cols[1]
        if not broker:
            continue
        try:
            price = float(cols[2].replace(",", ""))
            buy = int(float(cols[3].replace(",", "")))
            sell = int(float(cols[4].replace(",", "")))
        except ValueError:
            continue
        rows.append([broker, price, buy, sell])
    return pd.DataFrame(rows, columns=_COLUMNS)


def _parse_double(lines: list[str]) -> pd.DataFrame:
    """TWSE 舊式 big5 雙欄：每列含左（欄 1-4）右（欄 7-10）兩組資料。"""
    rows: list[list] = []
    for line in lines[3:]:  # 跳過表頭
        parts = line.strip().split(",")
        for base in (1, 7):
            if len(parts) >= base + 4 and parts[base].strip().strip('"'):
                try:
                    rows.append([
                        parts[base].strip().strip('"'),
                        float(parts[base + 1].strip('"')),
                        int(float(parts[base + 2].strip('"'))),
                        int(float(parts[base + 3].strip('"'))),
                    ])
                except ValueError:
                    pass
    return pd.DataFrame(rows, columns=_COLUMNS)


def _finalize(df: pd.DataFrame) -> pd.DataFrame:
    """統一型別並把股數 → 張。"""
    if df.empty:
        return df
    df = df.copy()
    df["Broker"] = df["Broker"].astype(str).str.strip()
    df["Price"] = df["Price"].astype(float)
    df["Buy"] = df["Buy"].astype(float) / 1000  # 股 → 張
    df["Sell"] = df["Sell"].astype(float) / 1000
    return df


def load_csv_bytes(
    raw: bytes,
    filename: str = "",
    market_override: str | None = None,
) -> tuple[pd.DataFrame, str, str | None, str | None]:
    """解析分點明細 CSV bytes。

    Returns
    -------
    df : pd.DataFrame
        欄位 ``[Broker, Price, Buy, Sell]``（單位：張）。
    market : str
        ``'TWSE'`` 或 ``'TPEX'``。
    stock_id : str | None
        優先取自 CSV 內代碼行，其次檔名。
    trade_date : str | None
        取自檔名（民國轉西元），無則 ``None``（由 OpenAPI 當日補上）。
    """
    text = _decode(raw)
    lines = text.splitlines()

    market, shape = detect_market(lines)
    if market_override:
        market = market_override.upper()

    if shape == "double":
        df = _parse_double(lines)
    else:
        df = _parse_single(lines)

    df = _finalize(df)

    stock_id = _extract_symbol(lines) or parse_filename(filename)[0]
    trade_date = parse_filename(filename)[1]
    return df, market, stock_id, trade_date


def load_csv(
    path: str, market_override: str | None = None
) -> tuple[pd.DataFrame, str, str | None, str | None]:
    """從檔案路徑解析（供 CLI / 測試使用）。"""
    import os

    with open(path, "rb") as f:
        raw = f.read()
    return load_csv_bytes(raw, os.path.basename(path), market_override)


def dataframe_from_rows(rows: list) -> pd.DataFrame:
    """把 OCR 自動抓取的分點 rows 轉為統一 DataFrame（單位：張）。

    每個 row 需具備 ``broker_code``/``broker_name`` (或 ``broker``)、``price``、
    ``buy_volume``、``sell_volume`` 屬性（或同名 dict 鍵），股數單位。
    相容 :class:`app.services.bsr_block_trades_service.BrokerTradeRow`。
    """
    def _get(row, *names):
        for n in names:
            if isinstance(row, dict):
                if n in row:
                    return row[n]
            elif hasattr(row, n):
                return getattr(row, n)
        return None

    parsed: list[list] = []
    for row in rows:
        code = _get(row, "broker_code", "code") or ""
        name = _get(row, "broker_name", "name") or ""
        broker = f"{code} {name}".strip() or str(_get(row, "broker") or "")
        price = _get(row, "price")
        buy = _get(row, "buy_volume", "buy")
        sell = _get(row, "sell_volume", "sell")
        if not broker or price is None:
            continue
        try:
            parsed.append([broker, float(price), int(float(buy or 0)), int(float(sell or 0))])
        except (ValueError, TypeError):
            continue
    df = pd.DataFrame(parsed, columns=_COLUMNS)
    return _finalize(df)


def clean_and_tag(df: pd.DataFrame, top_pct: float = 0.4):
    """Phase 1：同價位對沖 + 依「有效總量」取前 ``top_pct`` 主力。

    Returns
    -------
    df : pd.DataFrame
        含 Net_Buy / Eff_Buy / Eff_Sell / Eff_Total 欄位的清洗後資料。
    main_brokers : list[str]
        主力分點清單。
    hedged_volume : float
        被濾掉的同價對沖量（洗盤量，Phase 4 特徵之一）。
    """
    df = df.copy()
    df["Net_Buy"] = df["Buy"] - df["Sell"]
    df["Eff_Buy"] = df["Net_Buy"].clip(lower=0)
    df["Eff_Sell"] = (-df["Net_Buy"]).clip(lower=0)
    df["Eff_Total"] = df["Eff_Buy"] + df["Eff_Sell"]

    # 被濾掉的同價對沖量（買賣同時發生的重疊部分 × 2）
    hedged_volume = float((df[["Buy", "Sell"]].min(axis=1) * 2).sum())

    eff_by_broker = (
        df.groupby("Broker")["Eff_Total"].sum().sort_values(ascending=False)
    )
    n_main = max(1, int(len(eff_by_broker) * top_pct))
    main_brokers = eff_by_broker.head(n_main).index.tolist()
    return df, main_brokers, hedged_volume

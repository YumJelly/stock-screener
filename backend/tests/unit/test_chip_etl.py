"""Unit tests for the chip (籌碼) CSV parser (etl.load_csv_bytes).

Verifies that:
- TPEX broker-branch CSV is detected as TPEX regardless of encoding
  (fixes the tracker bug where Big5 files were misdetected as TWSE).
- UTF-8 and Big5 encodings of the same data parse identically.
- The stock code is read from the CSV content and the date from the filename.
- Buy/Sell volumes are converted from 股 to 張 (divided by 1000).
"""
from app.services.chip import etl

# 一份精簡的 TPEX 上櫃分點日報（格式同官網下載）
_TPEX_CSV = (
    "券商買賣證券成交價量資訊\n"
    "證券代碼,2230\n"
    "序號,券商,價格,買進股數,賣出股數\n"
    '"1","1021 合庫台中","25.80","1000","0"\n'
    '"2","1023 合庫高雄","25.55","0","2000"\n'
    '"3","8888 國泰敦南","25.70","3000","0"\n'
)


def _bytes(encoding: str) -> bytes:
    return _TPEX_CSV.encode(encoding)


def test_tpex_utf8_detected_and_parsed():
    raw = _bytes("utf-8")
    df, market, stock_id, trade_date = etl.load_csv_bytes(
        raw, "2230_1150703.csv"
    )
    assert market == "TPEX"
    assert stock_id == "2230"
    assert trade_date == "2026-07-03"
    assert len(df) == 3
    # 4000 股 → 4 張
    assert round(df["Buy"].sum(), 3) == 4.0
    assert round(df["Sell"].sum(), 3) == 2.0


def test_tpex_big5_not_misdetected_as_twse():
    raw = _bytes("big5")
    df, market, stock_id, _ = etl.load_csv_bytes(raw, "2230_1150703.csv")
    # Regression: Big5 TPEX file must NOT be misdetected as TWSE.
    assert market == "TPEX"
    assert stock_id == "2230"
    assert len(df) == 3


def test_utf8_and_big5_parse_identically():
    df_u, m_u, s_u, _ = etl.load_csv_bytes(_bytes("utf-8"), "2230_1150703.csv")
    df_b, m_b, s_b, _ = etl.load_csv_bytes(_bytes("big5"), "2230_1150703.csv")
    assert m_u == m_b == "TPEX"
    assert s_u == s_b == "2230"
    assert len(df_u) == len(df_b) == 3
    assert round(df_u["Buy"].sum(), 3) == round(df_b["Buy"].sum(), 3)
    assert round(df_u["Sell"].sum(), 3) == round(df_b["Sell"].sum(), 3)


def test_symbol_from_content_overrides_missing_filename():
    df, market, stock_id, trade_date = etl.load_csv_bytes(_bytes("utf-8"), "")
    assert stock_id == "2230"
    assert trade_date is None


def test_clean_and_tag_smoke():
    df, _, _, _ = etl.load_csv_bytes(_bytes("utf-8"), "2230_1150703.csv")
    cleaned, main_brokers, hedged = etl.clean_and_tag(df)
    assert "Net_Buy" in cleaned.columns
    assert "Eff_Total" in cleaned.columns
    assert len(main_brokers) >= 1
    assert hedged >= 0.0

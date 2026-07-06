"""Unit tests for chip tracking helpers (pure, no DB)."""
from app.services.chip import tracking


def test_bare_code_strips_market_suffix():
    assert tracking.bare_code("2330.TW") == "2330"
    assert tracking.bare_code("5483.TWO") == "5483"
    assert tracking.bare_code("2330") == "2330"
    assert tracking.bare_code(" 2330.tw ") == "2330"


def test_market_of_by_suffix():
    assert tracking.market_of("5483.TWO") == "TPEX"
    assert tracking.market_of("2330.TW") == "TWSE"
    assert tracking.market_of("2330") == "TWSE"


def test_is_taiwan_symbol():
    assert tracking.is_taiwan_symbol("2330.TW")
    assert tracking.is_taiwan_symbol("5483.TWO")
    assert not tracking.is_taiwan_symbol("AAPL")
    assert not tracking.is_taiwan_symbol("005930.KS")


def test_public_chart_url_requires_https(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "public_base_url", "", raising=False)
    assert tracking.public_chart_url("2330") is None

    monkeypatch.setattr(
        settings, "public_base_url", "http://insecure.example", raising=False
    )
    assert tracking.public_chart_url("2330") is None

    monkeypatch.setattr(
        settings, "public_base_url", "https://stocks.example.com/", raising=False
    )
    url = tracking.public_chart_url("2330.TW", "cumulative")
    assert url == (
        "https://stocks.example.com/api/v1/chip/chart/2330.png?kind=cumulative"
    )

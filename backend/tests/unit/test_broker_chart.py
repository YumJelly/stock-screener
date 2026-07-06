"""Unit tests for the chip broker-branch T-chart renderer (broker_chart).

Pure-logic tests (no DB): verify the top-20 broker selection by absolute net
and that :func:`render_t_chart` produces a valid PNG.
"""
import pandas as pd

from app.services.chip import broker_chart


def _sample_df(n_brokers: int = 25) -> pd.DataFrame:
    rows = []
    for i in range(n_brokers):
        broker = f"{1000 + i} 券商{i}"
        # 讓淨額隨 i 遞增，方便驗證 top-N 選取
        rows.append([broker, 100.0 + (i % 5), float(i * 10), 0.0])
        rows.append([broker, 110.0 + (i % 5), 0.0, float(i * 2)])
    return pd.DataFrame(rows, columns=["Broker", "Price", "Buy", "Sell"])


def test_build_matrices_top20_by_abs_net():
    df = _sample_df(25)
    top20, buy_m, sell_m = broker_chart._build_matrices(df)
    assert len(top20) == 20
    assert buy_m.shape == (20, 5)
    assert sell_m.shape == (20, 5)
    # 淨額最大的券商（i=24）必須入選；最小的（i=0）必須落選
    assert "1024 券商24" in top20
    assert "1000 券商0" not in top20


def test_render_t_chart_returns_png():
    df = _sample_df(25)
    png = broker_chart.render_t_chart(df, "測試 T 型圖")
    # PNG magic bytes
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(png) > 1000


def test_render_t_chart_empty_raises():
    empty = pd.DataFrame(columns=["Broker", "Price", "Buy", "Sell"])
    try:
        broker_chart.render_t_chart(empty, "空")
    except ValueError:
        return
    raise AssertionError("empty df should raise ValueError")


def test_stock_id_candidates_strips_suffix():
    assert broker_chart._stock_id_candidates("2330.TW")[0] == "2330.TW"
    assert "2330" in broker_chart._stock_id_candidates("2330.TW")
    assert "2330.TWO" in broker_chart._stock_id_candidates("2330")

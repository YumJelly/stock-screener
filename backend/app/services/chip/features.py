"""Chip pipeline Phase 3: 建構主力特徵矩陣（供 LLM 判讀的 JSON 輸入）。"""
from __future__ import annotations

import pandas as pd

from .zones import assign_zone


def build_features(
    df: pd.DataFrame,
    main_brokers: list[str],
    zones: dict,
    hedged_volume: float,
    ohlc: dict,
    prev_close: float,
) -> dict:
    """組出主力行為特徵矩陣。

    Parameters
    ----------
    ohlc : dict
        {'open':.., 'high':.., 'low':.., 'close':..}
    prev_close : float
        昨收價。
    """
    dm = df[df["Broker"].isin(main_brokers)].copy()
    dm["Zone"] = dm["Price"].apply(lambda p: assign_zone(p, zones))

    zone_net = dm.groupby("Zone")["Net_Buy"].sum().to_dict()
    zone_vol = dm.groupby("Zone")["Eff_Total"].sum().to_dict()

    bz = dm.groupby(["Broker", "Zone"])["Net_Buy"].sum().unstack(fill_value=0)
    for z in ("High", "Mid", "Low"):
        if z not in bz.columns:
            bz[z] = 0.0

    # 跨區間追蹤
    mask_a = (bz["High"] > 0) & (bz["Low"] < 0)  # 追高停損 / 高買低賣
    mask_b = (bz["High"] < 0) & (bz["Low"] > 0)  # 高賣低買
    feat_a_vol = float(bz.loc[mask_a, "High"].sum() - bz.loc[mask_a, "Low"].sum())
    feat_b_vol = float(-bz.loc[mask_b, "High"].sum() + bz.loc[mask_b, "Low"].sum())

    rng = ohlc["high"] - ohlc["low"]
    return {
        "zones": zones,
        "zone_net_buy": {k: round(v, 1) for k, v in zone_net.items()},
        "zone_eff_volume": {k: round(v, 1) for k, v in zone_vol.items()},
        "hedged_wash_volume": round(hedged_volume, 1),
        "cross_zone": {
            "high_buy_low_sell_count": int(mask_a.sum()),
            "high_buy_low_sell_volume": round(feat_a_vol, 1),
            "high_sell_low_buy_count": int(mask_b.sum()),
            "high_sell_low_buy_volume": round(feat_b_vol, 1),
        },
        "gap_anchor": round((ohlc["open"] - prev_close) / prev_close, 4)
        if prev_close
        else 0.0,
        "kline_shape": round((ohlc["close"] - ohlc["low"]) / rng, 3)
        if rng > 0
        else 0.5,
        "close_vs_prev": round((ohlc["close"] - prev_close) / prev_close, 4)
        if prev_close
        else 0.0,
        "top_players": {
            "high_zone_top_sellers": bz["High"].nsmallest(3).round(1).to_dict(),
            "high_zone_top_buyers": bz["High"].nlargest(3).round(1).to_dict(),
            "low_zone_top_buyers": bz["Low"].nlargest(3).round(1).to_dict(),
            "low_zone_top_sellers": bz["Low"].nsmallest(3).round(1).to_dict(),
        },
    }

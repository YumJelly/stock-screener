"""Chip pipeline Phase 2: K-Means 動態分區（High / Mid / Low 價位區間）。"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans


def learn_zones(df: pd.DataFrame, max_samples_per_price: int = 50000) -> dict:
    """以有效總量為權重，將價位分成 High / Mid / Low 三區。

    使用 KMeans 的 sample_weight 直接帶權重，避免展開樣本造成記憶體爆炸。

    Returns
    -------
    dict
        形如 {'High': {'min': .., 'max': ..}, 'Mid': {...}, 'Low': {...}}。
        資料不足時回傳空 dict。
    """
    price_eff = df.groupby("Price")["Eff_Total"].sum().reset_index()
    price_eff = price_eff[price_eff["Eff_Total"] > 0]
    if len(price_eff) < 3:
        return {}

    prices = price_eff["Price"].values.reshape(-1, 1)
    weights = price_eff["Eff_Total"].clip(upper=max_samples_per_price).values

    km = KMeans(n_clusters=3, random_state=42, n_init=10).fit(
        prices, sample_weight=weights
    )
    order = np.argsort(km.cluster_centers_.flatten())
    label_map = {order[0]: "Low", order[1]: "Mid", order[2]: "High"}
    price_eff = price_eff.copy()
    price_eff["Zone"] = [label_map[z] for z in km.predict(prices)]
    return (
        price_eff.groupby("Zone")["Price"]
        .agg(["min", "max"])
        .to_dict("index")
    )


def assign_zone(price: float, zones: dict) -> str:
    """依價位落點回傳所屬區間，無法歸類時回傳 'Mid'。"""
    for zone, bounds in zones.items():
        if bounds["min"] <= price <= bounds["max"]:
            return zone
    return "Mid"

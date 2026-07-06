"""Chip pipeline 計分：將 8 類機率映射為 +2 ~ -2 的主力企圖分數。"""
from __future__ import annotations

# 各分類的基準分數
BASE_SCORE = {
    "5": 2.0,   # 高檔追進（最多）
    "4": 1.0,   # 低檔吃貨
    "3": 0.0,   # 平盤交戰（零線）
    "8": 0.0,   # 低買高賣（洗盤區域，微調）
    "6": 0.0,   # 高買低賣（洗盤區域，微調）
    "7": 0.0,   # 高賣低買（洗盤區域，微調）
    "2": -1.0,  # 高檔出貨
    "1": -2.0,  # 低檔殺盤（最空）
}

# 零線族群的微調方向（依平盤區淨多/淨空 ±0.1）
NEUTRAL_ADJ = {"8": +0.1, "6": -0.1, "7": -0.1, "3": 0.0}


def daily_score(
    probabilities: dict, intensity: dict, mid_zone_net: float
) -> float:
    """計算當日總分，範圍限制在 [-2, 2]。"""
    score = 0.0
    for cls, p in probabilities.items():
        p = float(p)
        if cls in NEUTRAL_ADJ:
            adj = NEUTRAL_ADJ[cls]
            # 類別 3 依平盤區淨多/淨空 ±0.1
            if cls == "3":
                adj = 0.1 if mid_zone_net > 0 else (-0.1 if mid_zone_net < 0 else 0.0)
            score += p * adj
        else:
            base = BASE_SCORE.get(cls, 0.0)
            inten = float(intensity.get(cls, 0.5))
            score += p * base * inten
    return round(max(-2.0, min(2.0, score)), 2)

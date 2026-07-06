"""Chip pipeline Phase 4: Ollama 本地 LLM 推論，輸出 8 大分類機率與力道係數。

LLM 走遠端 Ollama（預設 http://134.208.2.6:11434），位址與模型可用環境變數覆寫：
- ``OLLAMA_API_BASE`` / ``CHIP_OLLAMA_URL``：Ollama 位址
- ``CHIP_OLLAMA_MODEL``：模型名稱（需支援 ``format=json``）
"""
from __future__ import annotations

import json
import os

import requests

from ...config import settings

DEFAULT_OLLAMA_BASE = "http://134.208.2.6:11434"
DEFAULT_MODEL = "qwen2.5:14b-instruct"

SYSTEM_PROMPT = """你是台股籌碼分析引擎。根據輸入的主力特徵矩陣（JSON），將當日主力行為分類為以下 8 類，輸出「機率分佈」與「力道係數」。

分類定義：
1 低檔殺盤：跌破昨收或開低，主力淨賣超集中於低檔區（不計成本棄守）
2 高檔出貨：股價拉升至高檔區，主力淨賣出異常集中（逢高調節）
3 平盤交戰：主力買賣在均價密集區交錯，有效交戰量與同價對沖量極大
4 低檔吃貨：股價落入低檔區，主力淨買進放大，日K留下影線（kline_shape 偏高）
5 高檔追進：主力在高檔區強勢淨買超，收盤維持高位（點火軋空）
6 高買低賣（當沖認賠）：大量主力高檔買、低檔賣，日K開高走低或留上影線
7 高賣低買（做空獲利）：大量主力高檔賣、低檔買
8 低買高賣（做多獲利）：大量主力低檔買、高檔賣以外的當沖多單獲利型態

規則：
- probabilities 八類總和必須等於 1.0
- 每個機率 > 0.05 的類別都要給 intensity（0.0~1.0）與一句 reasoning
- 只輸出 JSON，不要有任何其他文字或 markdown 標記

輸出格式：
{"probabilities": {"1": 0.0, "2": 0.0, "3": 0.0, "4": 0.0, "5": 0.0, "6": 0.0, "7": 0.0, "8": 0.0},
 "intensity": {"3": 0.85},
 "reasoning": {"3": "……"},
 "summary": "一段 80 字內的白話總結"}"""


def _chat_url() -> str:
    base = (
        os.environ.get("CHIP_OLLAMA_URL")
        or os.environ.get("OLLAMA_API_BASE")
        or getattr(settings, "chip_ollama_url", None)
        or DEFAULT_OLLAMA_BASE
    ).rstrip("/")
    if base.endswith("/api/chat"):
        return base
    return f"{base}/api/chat"


def _model() -> str:
    return (
        os.environ.get("CHIP_OLLAMA_MODEL")
        or getattr(settings, "chip_ollama_model", None)
        or DEFAULT_MODEL
    )


def classify(features: dict, timeout: int = 300) -> dict:
    """呼叫 Ollama 進行分類，回傳含正規化機率的結果 dict。"""
    resp = requests.post(
        _chat_url(),
        json={
            "model": _model(),
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(features, ensure_ascii=False),
                },
            ],
            "format": "json",  # 強制 JSON 輸出
            "stream": False,
            "options": {"temperature": 0.2, "num_ctx": 8192},
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    out = json.loads(resp.json()["message"]["content"])

    # 防呆：機率正規化，補齊 8 類
    probs = {
        str(k): max(0.0, float(v))
        for k, v in out.get("probabilities", {}).items()
    }
    for k in map(str, range(1, 9)):
        probs.setdefault(k, 0.0)
    s = sum(probs.values()) or 1.0
    out["probabilities"] = {k: round(v / s, 3) for k, v in probs.items()}
    return out


def generate(prompt: str, system: str | None = None, timeout: int = 120) -> str:
    """一般對話式生成（非 JSON），供 LINE Bot 個股分析使用。"""
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    resp = requests.post(
        _chat_url(),
        json={
            "model": _model(),
            "messages": messages,
            "stream": False,
            "options": {"temperature": 0.4, "num_ctx": 8192},
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()["message"]["content"].strip()

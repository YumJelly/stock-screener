"""Chip (籌碼) analysis module.

Ports the standalone ``tracker`` pipeline into the backend:
CSV / OCR 分點明細 → 對沖清洗 → 主力鎖定 → K-Means 動態分區 → 特徵矩陣 →
本地 LLM (Ollama) → 8 大分類機率 + 力道係數 → 當日總分 (+2 ~ -2)。

Public entry points live in :mod:`app.services.chip.pipeline`. Submodules are
imported lazily by callers to avoid pulling heavy deps (sklearn) or settings at
package-import time.
"""

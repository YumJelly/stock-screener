"""Chip (籌碼) daily analysis result model.

Stores one row per (stock_id, trade_date) with the LLM 8-class probabilities,
intensity, daily score (+2 ~ -2) and the full feature matrix / raw LLM output.
Ported from the standalone ``tracker`` SQLite ``daily_result`` table.
"""
from sqlalchemy import Column, DateTime, Float, Index, JSON, String, Text
from sqlalchemy.sql import func

from ..database import Base


class ChipDailyResult(Base):
    """單一股票單一交易日的籌碼判讀結果。"""

    __tablename__ = "chip_daily_result"

    stock_id = Column(String(20), primary_key=True, nullable=False)
    trade_date = Column(String(10), primary_key=True, nullable=False)  # YYYY-MM-DD

    market = Column(String(8), nullable=True)  # TWSE / TPEX
    score = Column(Float, nullable=False)      # +2 ~ -2

    probabilities = Column(JSON, nullable=True)  # {"1": .., ..., "8": ..}
    intensity = Column(JSON, nullable=True)      # {"3": 0.85, ..}
    summary = Column(Text, nullable=True)
    features = Column(JSON, nullable=True)       # 特徵矩陣
    raw_llm = Column(JSON, nullable=True)        # 完整 LLM 輸出

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("idx_chip_stock_date", "stock_id", "trade_date"),
    )

    def __repr__(self):
        return (
            f"<ChipDailyResult(stock_id='{self.stock_id}', "
            f"trade_date='{self.trade_date}', score={self.score})>"
        )

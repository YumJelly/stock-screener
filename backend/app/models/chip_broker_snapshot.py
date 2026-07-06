"""Chip (籌碼) raw broker-branch snapshot model.

Stores the raw per-broker/per-price ``[Broker, Price, Buy, Sell]`` rows (單位：張)
for one (stock_id, trade_date). This is the source data required to render the
「前 20 大主力分點對稱 T 型圖」 (both single-day and cumulative over a window).

The chip judgment pipeline (:mod:`app.services.chip.pipeline`) persists this
snapshot alongside the aggregated :class:`~app.models.chip_result.ChipDailyResult`.
Snapshots are retained indefinitely (never auto-cleaned) for historical charts.
"""
from sqlalchemy import Column, DateTime, Index, JSON, String
from sqlalchemy.sql import func

from ..database import Base


class ChipBrokerSnapshot(Base):
    """單一股票單一交易日的原始分點列（供繪製 T 型圖）。"""

    __tablename__ = "chip_broker_snapshot"

    stock_id = Column(String(20), primary_key=True, nullable=False)
    trade_date = Column(String(10), primary_key=True, nullable=False)  # YYYY-MM-DD

    market = Column(String(8), nullable=True)  # TWSE / TPEX
    source = Column(String(16), nullable=True)  # csv / twse_ocr / tpex
    # list[[broker:str, price:float, buy:float, sell:float]] — 單位：張
    rows = Column(JSON, nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("idx_chip_snapshot_stock_date", "stock_id", "trade_date"),
    )

    def __repr__(self):
        n = len(self.rows) if self.rows else 0
        return (
            f"<ChipBrokerSnapshot(stock_id='{self.stock_id}', "
            f"trade_date='{self.trade_date}', rows={n})>"
        )

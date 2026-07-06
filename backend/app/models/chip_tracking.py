"""Chip (籌碼) 30-day tracking enrollment model.

A stock enters tracking when it is queried on the LINE bot or added to a
front-end watchlist (Taiwan symbols only). While active, a daily Celery task
re-fetches broker-branch data (上市 TWSE auto; 上櫃 TPEX relies on manual CSV
upload), re-draws the cumulative T-chart and proactively pushes it to every
subscribed LINE user. When the cumulative chip score moves significantly it also
pushes a text alert.

One row per ``stock_id``; multiple LINE subscribers are stored in
``line_user_ids``. ``last_pushed_score`` tracks the last cumulative score that
was pushed so the daily task can detect significant changes.
"""
from sqlalchemy import Boolean, Column, DateTime, Float, Index, JSON, String
from sqlalchemy.sql import func

from ..database import Base


class ChipTracking(Base):
    """單一台股的 30 天籌碼追蹤登錄。"""

    __tablename__ = "chip_tracking"

    stock_id = Column(String(20), primary_key=True, nullable=False)

    market = Column(String(8), nullable=True)  # TWSE / TPEX
    # 訂閱推播的 LINE userId 清單（watchlist 觸發不會加入 userId）
    line_user_ids = Column(JSON, nullable=False, default=list)
    from_watchlist = Column(Boolean, nullable=False, default=False)

    start_date = Column(String(10), nullable=False)   # YYYY-MM-DD
    expires_at = Column(String(10), nullable=False)   # YYYY-MM-DD (start + 30d)
    active = Column(Boolean, nullable=False, default=True, index=True)

    # 上次推播時的累計分數（用來偵測顯著變化）
    last_pushed_score = Column(Float, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("idx_chip_tracking_active", "active", "market"),
    )

    def __repr__(self):
        return (
            f"<ChipTracking(stock_id='{self.stock_id}', active={self.active}, "
            f"expires_at='{self.expires_at}')>"
        )

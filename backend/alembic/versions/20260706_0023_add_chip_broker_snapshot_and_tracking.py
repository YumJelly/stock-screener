"""Add chip_broker_snapshot and chip_tracking tables.

- chip_broker_snapshot: raw per-broker/per-price rows (單位：張) for each
  (stock_id, trade_date), used to render the 前 20 大主力分點 T 型圖
  (single-day + cumulative). Retained indefinitely.
- chip_tracking: 30-day tracking enrollment triggered by LINE query or
  watchlist add (Taiwan symbols). Drives the daily re-fetch + proactive push.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260706_0023"
down_revision = "20260705_0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chip_broker_snapshot",
        sa.Column("stock_id", sa.String(length=20), nullable=False),
        sa.Column("trade_date", sa.String(length=10), nullable=False),
        sa.Column("market", sa.String(length=8), nullable=True),
        sa.Column("source", sa.String(length=16), nullable=True),
        sa.Column("rows", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("stock_id", "trade_date"),
    )
    op.create_index(
        "idx_chip_snapshot_stock_date",
        "chip_broker_snapshot",
        ["stock_id", "trade_date"],
    )

    op.create_table(
        "chip_tracking",
        sa.Column("stock_id", sa.String(length=20), nullable=False),
        sa.Column("market", sa.String(length=8), nullable=True),
        sa.Column("line_user_ids", sa.JSON(), nullable=False),
        sa.Column(
            "from_watchlist",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("start_date", sa.String(length=10), nullable=False),
        sa.Column("expires_at", sa.String(length=10), nullable=False),
        sa.Column(
            "active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column("last_pushed_score", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("stock_id"),
    )
    op.create_index(
        "idx_chip_tracking_active", "chip_tracking", ["active", "market"]
    )


def downgrade() -> None:
    op.drop_index("idx_chip_tracking_active", table_name="chip_tracking")
    op.drop_table("chip_tracking")
    op.drop_index(
        "idx_chip_snapshot_stock_date", table_name="chip_broker_snapshot"
    )
    op.drop_table("chip_broker_snapshot")

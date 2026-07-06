"""Add chip_daily_result table for 籌碼 (chip) daily analysis results.

Ported from the standalone ``tracker`` SQLite ``daily_result`` table.
One row per (stock_id, trade_date) with LLM 8-class probabilities, intensity,
daily score (+2 ~ -2), feature matrix and raw LLM output.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260705_0022"
down_revision = "20260614_0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chip_daily_result",
        sa.Column("stock_id", sa.String(length=20), nullable=False),
        sa.Column("trade_date", sa.String(length=10), nullable=False),
        sa.Column("market", sa.String(length=8), nullable=True),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("probabilities", sa.JSON(), nullable=True),
        sa.Column("intensity", sa.JSON(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("features", sa.JSON(), nullable=True),
        sa.Column("raw_llm", sa.JSON(), nullable=True),
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
        "idx_chip_stock_date", "chip_daily_result", ["stock_id", "trade_date"]
    )


def downgrade() -> None:
    op.drop_index("idx_chip_stock_date", table_name="chip_daily_result")
    op.drop_table("chip_daily_result")

"""Add TW-specific CNYes data: monthly revenue, ESG grade, broker ratings table.

New columns on stock_fundamentals:
  tw_revenue_monthly_latest, tw_revenue_monthly_yoy, tw_revenue_monthly_mom,
  tw_revenue_monthly_date, tw_revenue_monthly_updated_at,
  tw_esg_grade, tw_esg_updated_at

New table:
  tw_broker_ratings (symbol, format_date, broker, rate_kind, new_rate, target_price, fetched_at)
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260614_0021"
down_revision = "20260601_0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- stock_fundamentals: 月營收 columns ---
    op.add_column(
        "stock_fundamentals",
        sa.Column("tw_revenue_monthly_latest", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "stock_fundamentals",
        sa.Column("tw_revenue_monthly_yoy", sa.Float(), nullable=True),
    )
    op.add_column(
        "stock_fundamentals",
        sa.Column("tw_revenue_monthly_mom", sa.Float(), nullable=True),
    )
    op.add_column(
        "stock_fundamentals",
        sa.Column("tw_revenue_monthly_date", sa.String(length=10), nullable=True),
    )
    op.add_column(
        "stock_fundamentals",
        sa.Column("tw_revenue_monthly_updated_at", sa.DateTime(timezone=True), nullable=True),
    )

    # --- stock_fundamentals: ESG columns ---
    op.add_column(
        "stock_fundamentals",
        sa.Column("tw_esg_grade", sa.String(length=5), nullable=True),
    )
    op.add_column(
        "stock_fundamentals",
        sa.Column("tw_esg_updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_stock_fundamentals_tw_esg_grade",
        "stock_fundamentals",
        ["tw_esg_grade"],
    )

    # --- new table: tw_broker_ratings ---
    op.create_table(
        "tw_broker_ratings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(length=20), nullable=False),
        sa.Column("format_date", sa.String(length=12), nullable=False),
        sa.Column("broker", sa.String(length=50), nullable=True),
        sa.Column("rate_kind", sa.String(length=20), nullable=True),
        sa.Column("new_rate", sa.String(length=20), nullable=True),
        sa.Column("target_price", sa.Float(), nullable=True),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "symbol", "format_date", "broker",
            name="uix_tw_broker_symbol_date_broker",
        ),
    )
    op.create_index("idx_tw_broker_symbol", "tw_broker_ratings", ["symbol"])
    op.create_index("idx_tw_broker_date", "tw_broker_ratings", ["format_date"])


def downgrade() -> None:
    # Drop tw_broker_ratings table
    op.drop_index("idx_tw_broker_date", table_name="tw_broker_ratings")
    op.drop_index("idx_tw_broker_symbol", table_name="tw_broker_ratings")
    op.drop_table("tw_broker_ratings")

    # Drop ESG columns
    op.drop_index(
        "ix_stock_fundamentals_tw_esg_grade", table_name="stock_fundamentals"
    )
    op.drop_column("stock_fundamentals", "tw_esg_updated_at")
    op.drop_column("stock_fundamentals", "tw_esg_grade")

    # Drop 月營收 columns
    op.drop_column("stock_fundamentals", "tw_revenue_monthly_updated_at")
    op.drop_column("stock_fundamentals", "tw_revenue_monthly_date")
    op.drop_column("stock_fundamentals", "tw_revenue_monthly_mom")
    op.drop_column("stock_fundamentals", "tw_revenue_monthly_yoy")
    op.drop_column("stock_fundamentals", "tw_revenue_monthly_latest")

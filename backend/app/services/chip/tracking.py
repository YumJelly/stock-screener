"""Chip 30 天追蹤登錄與推播工具。

- :func:`enroll`：LINE 詢問 / watchlist 加入台股時登錄追蹤（idempotent，延展效期）。
- :func:`public_chart_url`：組出公開 HTTPS 的 T 型圖網址（供 LINE image message）。
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

from sqlalchemy.orm import Session

from ...config import settings
from ...models.chip_tracking import ChipTracking

logger = logging.getLogger(__name__)


def bare_code(symbol: str) -> str:
    """去除市場後綴，回傳純代號（2330.TW → 2330）。"""
    sid = (symbol or "").strip().upper()
    for suf in (".TW", ".TWO"):
        if sid.endswith(suf):
            return sid[: -len(suf)]
    return sid


def market_of(symbol: str, default: str = "TWSE") -> str:
    """依後綴判斷市場（.TWO → TPEX，其餘 → default）。"""
    return "TPEX" if (symbol or "").strip().upper().endswith(".TWO") else default


def is_taiwan_symbol(symbol: str) -> bool:
    s = (symbol or "").strip().upper()
    return s.endswith(".TW") or s.endswith(".TWO")


def enroll(
    db: Session,
    stock_id: str,
    market: str,
    line_user_id: str | None = None,
    from_watchlist: bool = False,
) -> ChipTracking:
    """登錄／續訂某台股的 30 天追蹤（以純代號為鍵，idempotent）。"""
    code = bare_code(stock_id)
    today = date.today()
    expires = today + timedelta(days=settings.chip_tracking_days)

    row = (
        db.query(ChipTracking)
        .filter(ChipTracking.stock_id == code)
        .one_or_none()
    )
    if row is None:
        row = ChipTracking(
            stock_id=code,
            market=market,
            line_user_ids=[line_user_id] if line_user_id else [],
            from_watchlist=from_watchlist,
            start_date=today.isoformat(),
            expires_at=expires.isoformat(),
            active=True,
        )
        db.add(row)
    else:
        row.active = True
        row.market = market or row.market
        row.expires_at = expires.isoformat()  # 續訂：重新起算 30 天
        if from_watchlist:
            row.from_watchlist = True
        if line_user_id:
            users = list(row.line_user_ids or [])
            if line_user_id not in users:
                users.append(line_user_id)
            row.line_user_ids = users
    db.commit()
    db.refresh(row)
    return row


def public_chart_url(stock_id: str, kind: str = "daily") -> str | None:
    """組出公開 HTTPS 的 T 型圖網址；未設定 public_base_url 時回 None。"""
    base = (settings.public_base_url or "").rstrip("/")
    if not base.lower().startswith("https://"):
        return None
    code = bare_code(stock_id)
    return f"{base}/api/v1/chip/chart/{code}.png?kind={kind}"


def list_for_user(db: Session, line_user_id: str) -> list[ChipTracking]:
    """回傳某 LINE 使用者目前 active 的追蹤股（依到期日排序）。"""
    if not line_user_id:
        return []
    rows = (
        db.query(ChipTracking)
        .filter(ChipTracking.active.is_(True))
        .all()
    )
    mine = [r for r in rows if line_user_id in (r.line_user_ids or [])]
    mine.sort(key=lambda r: r.expires_at or "")
    return mine


def remove_for_user(db: Session, stock_id: str, line_user_id: str) -> bool:
    """把某使用者從某台股的追蹤中移除。

    - 從 ``line_user_ids`` 移除該 userId。
    - 若移除後已無任何訂閱者且非來自 watchlist → 整筆停用（active=False）。

    Returns
    -------
    bool
        True 表示原本有追蹤且已移除；False 表示原本就沒在追蹤。
    """
    code = bare_code(stock_id)
    row = (
        db.query(ChipTracking)
        .filter(ChipTracking.stock_id == code, ChipTracking.active.is_(True))
        .one_or_none()
    )
    if row is None or line_user_id not in (row.line_user_ids or []):
        return False

    users = [u for u in (row.line_user_ids or []) if u != line_user_id]
    row.line_user_ids = users
    if not users and not row.from_watchlist:
        row.active = False
    db.commit()
    return True



"""Public chip chart endpoint (分點 T 型圖 PNG).

Kept in its own router so it can be mounted **unauthenticated** — LINE's servers
must be able to fetch the image via ``originalContentUrl`` without a session
cookie. Only returns rendered PNGs; no sensitive data is exposed.

GET /v1/chip/chart/{stock_id}.png?kind=daily|cumulative&date=YYYY-MM-DD
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session

from ...database import get_db
from ...services.chip import broker_chart

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get(
    "/chip/chart/{stock_id}.png",
    summary="前 20 大主力分點對稱 T 型圖（PNG，公開）",
    response_class=Response,
)
def get_chart(
    stock_id: str,
    kind: str = "daily",
    date: str | None = None,
    db: Session = Depends(get_db),
):
    """回傳分點 T 型圖 PNG。

    - ``kind=daily``：單一交易日（``date`` 省略取最新一日）。
    - ``kind=cumulative``：追蹤視窗內多日彙整（累計）。
    """
    sid = stock_id.strip().upper()
    try:
        if kind == "cumulative":
            png = broker_chart.build_cumulative_chart(db, sid)
        else:
            png = broker_chart.build_daily_chart(db, sid, date)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("chip chart render failed for %s", sid)
        raise HTTPException(status_code=500, detail=f"繪圖失敗：{exc}") from exc

    return Response(
        content=png,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=300"},
    )

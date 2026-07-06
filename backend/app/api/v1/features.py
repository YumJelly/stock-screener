"""Feature store API endpoints.

Provides monitoring and comparison capabilities for the feature store:
- GET /features/runs — list feature runs with row counts
- GET /features/runs/active — active run progress (done/total/pct)
- GET /features/compare — compare two feature runs side-by-side
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Optional, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text

from ...schemas.feature_store import (
    CompareRunsResponse,
    FeatureRunResponse,
    ListRunsResponse,
)
from ...wiring.bootstrap import (
    get_compare_feature_runs_use_case,
    get_list_feature_runs_use_case,
    get_uow,
)

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/runs/active")
async def get_active_run_progress(uow: Any = Depends(get_uow)):
    """Return progress of the currently running feature snapshot (done/total/pct).

    Returns null fields when no run is active.
    """
    with uow:
        db = uow.session
        row = db.execute(text("""
            SELECT
                fr.id,
                fr.as_of_date,
                fr.status,
                fr.created_at,
                (SELECT COUNT(*) FROM stock_feature_daily WHERE run_id = fr.id) AS done,
                (SELECT COUNT(*) FROM feature_run_universe_symbols WHERE run_id = fr.id) AS total
            FROM feature_runs fr
            WHERE fr.status = 'running'
            ORDER BY fr.created_at DESC
            LIMIT 1
        """)).mappings().first()

    if row is None:
        return {"active": False, "run": None}

    done = row["done"] or 0
    total = row["total"] or 0
    pct = round(done / total * 100, 1) if total > 0 else 0.0
    return {
        "active": True,
        "run": {
            "id": row["id"],
            "as_of_date": str(row["as_of_date"]),
            "status": row["status"],
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            "done": done,
            "total": total,
            "pct": pct,
        },
    }


@router.post("/runs/active/cancel")
async def cancel_active_run(uow: Any = Depends(get_uow)):
    """Mark any currently-running feature snapshot run as failed.

    Safe to call at any time — only affects rows with status='running'.
    Used by the Operations UI to clear a stuck snapshot progress card.
    """
    with uow:
        db = uow.session
        result = db.execute(text("""
            UPDATE feature_runs
            SET status = 'failed'
            WHERE status = 'running'
        """))
        db.commit()
        cancelled = result.rowcount
    return {"cancelled": cancelled}


@router.get("/runs", response_model=ListRunsResponse)
async def list_runs(
    status: Optional[str] = Query(None, description="Filter by run status"),
    date_from: Optional[date] = Query(None, description="Start date (inclusive)"),
    date_to: Optional[date] = Query(None, description="End date (inclusive)"),
    limit: int = Query(50, ge=1, le=200, description="Max runs to return"),
    uow: Any = Depends(get_uow),
    use_case: Any = Depends(get_list_feature_runs_use_case),
):
    """List feature runs with row counts and publish status."""
    try:
        from ...domain.common.errors import ValidationError as DomainValidationError
        from ...use_cases.feature_store.list_runs import ListRunsQuery

        query = ListRunsQuery(
            status=status,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
        )
        result = use_case.execute(uow, query)
    except DomainValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    runs = [FeatureRunResponse.from_domain(r) for r in result.runs]
    return ListRunsResponse(runs=runs)


@router.get("/compare", response_model=CompareRunsResponse)
async def compare_runs(
    run_a: int = Query(..., description="First run ID (baseline)"),
    run_b: int = Query(..., description="Second run ID (comparison)"),
    limit: int = Query(50, ge=1, le=500, description="Max movers to return"),
    uow: Any = Depends(get_uow),
    use_case: Any = Depends(get_compare_feature_runs_use_case),
):
    """Compare two feature runs: added/removed symbols and score movers."""
    try:
        from ...domain.common.errors import (
            EntityNotFoundError,
            ValidationError as DomainValidationError,
        )
        from ...use_cases.feature_store.compare_runs import CompareRunsQuery

        query = CompareRunsQuery(run_a=run_a, run_b=run_b, limit=limit)
        result = use_case.execute(uow, query)
    except DomainValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except EntityNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return CompareRunsResponse.from_domain(result)

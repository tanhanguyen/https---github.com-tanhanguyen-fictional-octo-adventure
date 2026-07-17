from __future__ import annotations

import json
import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from bot.api.deps import get_runner_service
from bot.api.run_service import RunnerService
from bot.api.schemas import (
    DecisionDetailOut,
    DecisionFilterOut,
    DecisionOut,
    DecisionStatsOut,
)

router = APIRouter()


def _row_to_decision(row: sqlite3.Row) -> DecisionOut:
    return DecisionOut(
        id=row["id"],
        run_id=row["run_id"],
        bar_ts_utc=row["bar_ts_utc"],
        reason=row["reason"],
        stage=row["stage"],
        detail=row["detail"],
        strategy=row["strategy"],
        direction=row["direction"],
        trade_id=row["trade_id"],
    )


@router.get("/decisions", response_model=list[DecisionOut])
def list_decisions(
    limit: int = 50,
    reason: str | None = None,
    outcome: str | None = None,
    service: RunnerService = Depends(get_runner_service),
) -> list[DecisionOut]:
    return [_row_to_decision(r) for r in service.list_decisions(limit, reason, outcome)]


@router.get("/decisions/stats", response_model=DecisionStatsOut)
def decisions_stats(service: RunnerService = Depends(get_runner_service)) -> DecisionStatsOut:
    return DecisionStatsOut(histogram=service.decision_stats())


@router.get("/decisions/{decision_id}", response_model=DecisionDetailOut)
def get_decision(
    decision_id: int, service: RunnerService = Depends(get_runner_service)
) -> DecisionDetailOut:
    row = service.get_decision(decision_id)
    if row is None:
        raise HTTPException(status_code=404, detail="decision not found")
    filter_rows = [
        DecisionFilterOut(
            id=f["id"],
            filter_id=f["filter_id"],
            kind=f["kind"],
            enabled=bool(f["enabled"]),
            evaluated=bool(f["evaluated"]),
            passed=None if f["passed"] is None else bool(f["passed"]),
            blocking=bool(f["blocking"]),
            values=json.loads(f["values_json"]) if f["values_json"] else {},
            detail=f["detail"],
        )
        for f in service.list_decision_filters(decision_id)
    ]
    base = _row_to_decision(row)
    return DecisionDetailOut(**base.model_dump(), filters=filter_rows)

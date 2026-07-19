"""Run registry (plan 03): read-only access to ANY run in the DB, active or not.
The mutable single-active-run endpoints stay in routers/run.py."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from bot.analytics.metrics import RunReport
from bot.api.deps import get_runner_service
from bot.api.routers.decisions import _row_to_decision
from bot.api.routers.trades import _row_to_trade
from bot.api.run_service import RunnerService
from bot.api.schemas import (
    BarOut,
    DecisionOut,
    EquityPointOut,
    RunCompareOut,
    RunReportOut,
    RunSummaryOut,
    SeriesStatsOut,
    TradeOut,
    TradeStatsOut,
)
from bot.core.errors import ConfigError

router = APIRouter()


def _require_run(service: RunnerService, run_id: int) -> None:
    if service.get_run_row(run_id) is None:
        raise HTTPException(status_code=404, detail="run not found")


def _report_out(run_id: int, report: RunReport) -> RunReportOut:
    return RunReportOut(
        run_id=run_id,
        overall=TradeStatsOut.model_validate(asdict(report.overall)),
        per_strategy={
            k: TradeStatsOut.model_validate(asdict(v)) for k, v in report.per_strategy.items()
        },
        series=SeriesStatsOut.model_validate(asdict(report.series)),
        reason_histogram=report.reason_histogram,
        filter_block_counts=report.filter_block_counts,
    )


@router.get("/runs", response_model=list[RunSummaryOut])
def list_runs(service: RunnerService = Depends(get_runner_service)) -> list[RunSummaryOut]:
    return [RunSummaryOut(**r) for r in service.list_runs()]


@router.get("/runs/compare", response_model=RunCompareOut)
def compare_runs(
    a: int = Query(...),
    b: int = Query(...),
    service: RunnerService = Depends(get_runner_service),
) -> RunCompareOut:
    try:
        result: dict[str, Any] = service.compare_runs(a, b)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"run {exc.args[0]} not found") from exc
    return RunCompareOut(**result)


@router.get("/runs/{run_id}/report", response_model=RunReportOut)
def run_report(
    run_id: int, service: RunnerService = Depends(get_runner_service)
) -> RunReportOut:
    try:
        report = service.run_report(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="run not found") from exc
    return _report_out(run_id, report)


@router.get("/runs/{run_id}/trades", response_model=list[TradeOut])
def run_trades(
    run_id: int,
    status: str | None = None,
    service: RunnerService = Depends(get_runner_service),
) -> list[TradeOut]:
    _require_run(service, run_id)
    return [_row_to_trade(r) for r in service.list_trades(status, run_id=run_id)]


@router.get("/runs/{run_id}/decisions", response_model=list[DecisionOut])
def run_decisions(
    run_id: int,
    limit: int = 50,
    reason: str | None = None,
    outcome: str | None = None,
    service: RunnerService = Depends(get_runner_service),
) -> list[DecisionOut]:
    _require_run(service, run_id)
    return [_row_to_decision(r) for r in service.list_decisions(limit, reason, outcome, run_id)]


@router.get("/runs/{run_id}/equity", response_model=list[EquityPointOut])
def run_equity(
    run_id: int,
    limit: int = 500,
    service: RunnerService = Depends(get_runner_service),
) -> list[EquityPointOut]:
    _require_run(service, run_id)
    return [
        EquityPointOut(bar_ts_utc=r["bar_ts_utc"], equity=r["equity"], balance=r["balance"])
        for r in service.list_equity_points(limit, run_id=run_id)
    ]


@router.get("/runs/{run_id}/bars", response_model=list[BarOut])
def run_bars(
    run_id: int,
    tf: str = "1H",
    from_ts: str | None = Query(None, alias="from"),
    to_ts: str | None = Query(None, alias="to"),
    limit: int = Query(1000, ge=1, le=20000),
    service: RunnerService = Depends(get_runner_service),
) -> list[BarOut]:
    try:
        bars = service.run_bars(run_id, tf, from_ts, to_ts, limit)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="run not found") from exc
    except ConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return [BarOut(**b) for b in bars]


@router.delete("/runs/{run_id}")
def delete_run(
    run_id: int, service: RunnerService = Depends(get_runner_service)
) -> dict[str, str]:
    try:
        service.delete_run(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="run not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"status": "deleted"}

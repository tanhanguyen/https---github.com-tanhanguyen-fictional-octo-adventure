"""Sweep registry (plan 11 §3): READ-ONLY.

There is deliberately no POST: a sweep is hours of CPU and hundreds of runs, driven by
`python -m bot.cli sweep --config sweeps/<spec>.yaml`. The web page reads the result and
links each row to that run's Report page.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from bot.api.deps import get_runner_service
from bot.api.run_service import RunnerService
from bot.api.schemas import SweepDetailOut, SweepSummaryOut

router = APIRouter()


@router.get("/sweeps", response_model=list[SweepSummaryOut])
def list_sweeps(service: RunnerService = Depends(get_runner_service)) -> list[SweepSummaryOut]:
    return [SweepSummaryOut(**s) for s in service.list_sweeps()]


@router.get("/sweeps/{sweep_id}", response_model=SweepDetailOut)
def get_sweep(
    sweep_id: int, service: RunnerService = Depends(get_runner_service)
) -> SweepDetailOut:
    try:
        return SweepDetailOut(**service.get_sweep(sweep_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="sweep not found") from exc

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from bot.api.deps import get_runner_service
from bot.api.run_service import RunnerService
from bot.api.schemas import PlayIn, RunCreateIn, RunOut, RunStepOut

router = APIRouter()


def _run_out(info: dict[str, Any]) -> RunOut:
    return RunOut(**info)


@router.get("/run", response_model=RunOut | None)
def get_run(service: RunnerService = Depends(get_runner_service)) -> RunOut | None:
    info = service.get_run()
    return _run_out(info) if info else None


@router.post("/run", response_model=RunOut)
def create_run(
    body: RunCreateIn | None = None, service: RunnerService = Depends(get_runner_service)
) -> RunOut:
    body = body or RunCreateIn()
    info = service.create_run(seed=body.seed, bars=body.bars, dataset_id=body.dataset_id)
    return _run_out(info)


@router.post("/run/step", response_model=RunStepOut)
def step(service: RunnerService = Depends(get_runner_service)) -> RunStepOut:
    try:
        summary = service.step()
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if summary is None:
        return RunStepOut(
            bar_ts="",
            reason="done",
            stage="feed_exhausted",
            trade_event_types=[],
            closed_result=None,
            equity=0.0,
            exhausted=True,
        )
    return RunStepOut(
        bar_ts=summary.bar_ts,
        reason=summary.reason,
        stage=summary.stage,
        trade_event_types=summary.trade_event_types,
        closed_result=summary.closed_result,
        equity=summary.equity,
        exhausted=False,
    )


@router.post("/run/play", response_model=RunOut)
def play(
    body: PlayIn | None = None, service: RunnerService = Depends(get_runner_service)
) -> RunOut:
    body = body or PlayIn()
    try:
        service.play(interval_ms=body.interval_ms)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    info = service.get_run()
    assert info is not None
    return _run_out(info)


@router.post("/run/pause", response_model=RunOut | None)
def pause(service: RunnerService = Depends(get_runner_service)) -> RunOut | None:
    service.pause()
    info = service.get_run()
    return _run_out(info) if info else None


@router.post("/run/reset")
def reset(service: RunnerService = Depends(get_runner_service)) -> dict[str, str]:
    service.reset()
    return {"status": "reset"}

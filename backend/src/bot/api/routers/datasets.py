from __future__ import annotations

from fastapi import APIRouter, Depends

from bot.api.deps import get_runner_service
from bot.api.run_service import RunnerService
from bot.api.schemas import DatasetCreateIn, DatasetOut

router = APIRouter()


@router.get("/datasets", response_model=list[DatasetOut])
def list_datasets(service: RunnerService = Depends(get_runner_service)) -> list[DatasetOut]:
    return [DatasetOut(**d) for d in service.list_datasets()]


@router.post("/datasets", response_model=DatasetOut)
def create_dataset(
    body: DatasetCreateIn | None = None,
    service: RunnerService = Depends(get_runner_service),
) -> DatasetOut:
    body = body or DatasetCreateIn()
    _row, cfg = service.get_active_config()
    did = service.create_dataset(
        body.seed,
        body.bars,
        cfg.symbol,
        cfg.trading_day_rollover_tz,
        cfg.trading_day_rollover_time,
    )
    match = next(d for d in service.list_datasets() if d["id"] == did)
    return DatasetOut(**match)

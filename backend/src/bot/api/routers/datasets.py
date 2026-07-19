from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from bot.api.deps import get_runner_service
from bot.api.run_service import RunnerService
from bot.api.schemas import DatasetCreateIn, DatasetImportIn, DatasetOut
from bot.core.errors import FeedError

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


@router.post("/datasets/import", response_model=DatasetOut)
def import_dataset(
    body: DatasetImportIn, service: RunnerService = Depends(get_runner_service)
) -> DatasetOut:
    try:
        result = service.import_csv(body.path, body.symbol, body.native_tf)
    except FeedError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=422, detail=f"file not found: {body.path}") from exc
    # Idempotent re-import may return a row registered under a different path/spelling,
    # so match by dataset id -- not by source_path.
    match = next(d for d in service.list_datasets() if d["id"] == result.dataset_id)
    return DatasetOut(**match)

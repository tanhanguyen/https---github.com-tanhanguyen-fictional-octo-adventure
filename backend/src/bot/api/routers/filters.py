from __future__ import annotations

from fastapi import APIRouter, Depends

from bot.api.deps import get_runner_service
from bot.api.run_service import RunnerService
from bot.api.schemas import FilterRowOut

router = APIRouter()


@router.get("/filters", response_model=list[FilterRowOut])
def list_filters(service: RunnerService = Depends(get_runner_service)) -> list[FilterRowOut]:
    return [FilterRowOut(**row) for row in service.filters_snapshot()]

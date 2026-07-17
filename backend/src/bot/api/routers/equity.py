from __future__ import annotations

from fastapi import APIRouter, Depends

from bot.api.deps import get_runner_service
from bot.api.run_service import RunnerService
from bot.api.schemas import EquityPointOut, SymbolOut

router = APIRouter()


@router.get("/equity", response_model=list[EquityPointOut])
def get_equity(
    limit: int = 500, service: RunnerService = Depends(get_runner_service)
) -> list[EquityPointOut]:
    return [
        EquityPointOut(bar_ts_utc=r["bar_ts_utc"], equity=r["equity"], balance=r["balance"])
        for r in service.list_equity_points(limit)
    ]


@router.get("/symbols", response_model=list[SymbolOut])
def get_symbols(service: RunnerService = Depends(get_runner_service)) -> list[SymbolOut]:
    return [SymbolOut(**s) for s in service.list_symbols()]

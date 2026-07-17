from __future__ import annotations

from fastapi import APIRouter, Depends

from bot.api.deps import get_runner_service
from bot.api.run_service import RunnerService
from bot.api.schemas import AccountOut

router = APIRouter()


@router.get("/account", response_model=AccountOut)
def get_account(service: RunnerService = Depends(get_runner_service)) -> AccountOut:
    return AccountOut(**service.account_snapshot())

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from bot.api.deps import get_runner_service
from bot.api.run_service import RunnerService
from bot.api.schemas import TradeDetailOut, TradeEventOut, TradeOut

router = APIRouter()


def _row_to_trade(row: sqlite3.Row) -> TradeOut:
    return TradeOut(
        id=row["id"],
        run_id=row["run_id"],
        symbol=row["symbol"],
        strategy=row["strategy"],
        direction=row["direction"],
        status=row["status"],
        entry_price=row["entry_price"],
        sl_price=row["sl_price"],
        tp1_price=row["tp1_price"],
        tp2_price=row["tp2_price"],
        lot_size=row["lot_size"],
        opened_at_utc=row["opened_at_utc"],
        closed_at_utc=row["closed_at_utc"],
        trading_day=row["trading_day"],
        result=row["result"],
        pnl_amount=row["pnl_amount"],
        pnl_r=row["pnl_r"],
        decision_id=row["decision_id"],
    )


@router.get("/trades", response_model=list[TradeOut])
def list_trades(
    status: str | None = None,
    symbol: str | None = None,
    service: RunnerService = Depends(get_runner_service),
) -> list[TradeOut]:
    return [_row_to_trade(r) for r in service.list_trades(status, symbol=symbol)]


@router.get("/trades/{trade_id}", response_model=TradeDetailOut)
def get_trade(
    trade_id: int, service: RunnerService = Depends(get_runner_service)
) -> TradeDetailOut:
    row = service.get_trade(trade_id)
    if row is None:
        raise HTTPException(status_code=404, detail="trade not found")
    events = [
        TradeEventOut(
            id=e["id"],
            event_type=e["event_type"],
            ts_utc=e["ts_utc"],
            price=e["price"],
            detail=e["detail"],
        )
        for e in service.list_trade_events(trade_id)
    ]
    base = _row_to_trade(row)
    return TradeDetailOut(**base.model_dump(), trade_events=events)

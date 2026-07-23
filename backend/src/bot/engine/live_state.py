"""Serialising a live run's in-memory state to `strategy_state` (plan 07 §2).

Recovery choice, recorded in docs/decisions.md: after a restart the state machine is
**restored from the DB**, not rebuilt by re-running `decide()` over the last K bars.
Re-running is attractive (no new table) but it drifts: the retest state machine is
path-dependent over an unbounded window, so a K-bar replay can land in a different
state than the one that was actually live — and a wrong retest state silently changes
which trades get taken.

What is persisted per symbol, once per processed bar (a bar is cheap; correctness after
an unplanned kill is not):

  * the breakout-retest state machine,
  * the in-flight `OpenTrade` **in full** (not just its `trade` row: `tp_rules`,
    `remaining_fraction`, realized partials and the settlement counters have no columns
    and cannot be reconstructed from the row),
  * the symbol cursor, so processing resumes on exactly the next bar,
  * balance/equity, which are the account scalars the Runner carries between bars.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

from bot.core.types import Direction, OrderStatus, StrategyName, TPRules
from bot.engine.order_engine import OpenTrade
from bot.strategies.base import BreakoutState

#: Bumped whenever the payload shape changes; an unknown version is treated as "no
#: state" rather than being guessed at (fail-closed: the runner refuses to resume).
STATE_VERSION = 1


def _dt(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def _parse_dt(value: str | None) -> datetime | None:
    return None if value is None else datetime.fromisoformat(value)


def _date(value: date | None) -> str | None:
    return None if value is None else value.isoformat()


def _parse_date(value: str | None) -> date | None:
    return None if value is None else date.fromisoformat(value)


def breakout_state_to_dict(state: BreakoutState) -> dict[str, Any]:
    return {
        "status": state.status,
        "direction": state.direction.value if state.direction else None,
        "range_high": state.range_high,
        "range_low": state.range_low,
        "breakout_bar_ts": _dt(state.breakout_bar_ts),
        "bars_waited": state.bars_waited,
    }


def breakout_state_from_dict(data: dict[str, Any]) -> BreakoutState:
    return BreakoutState(
        status=data["status"],
        direction=Direction(data["direction"]) if data["direction"] else None,
        range_high=data["range_high"],
        range_low=data["range_low"],
        breakout_bar_ts=_parse_dt(data["breakout_bar_ts"]),
        bars_waited=data["bars_waited"],
    )


def trade_to_dict(trade: OpenTrade | None) -> dict[str, Any] | None:
    if trade is None:
        return None
    return {
        "local_id": trade.local_id,
        "symbol": trade.symbol,
        "strategy": trade.strategy.value,
        "direction": trade.direction.value,
        "status": trade.status.value,
        "sl": trade.sl,
        "tp_rules": {
            "kind": trade.tp_rules.kind,
            "tp1_r": trade.tp_rules.tp1_r,
            "tp2_r": trade.tp_rules.tp2_r,
            "tp1_abs": trade.tp_rules.tp1_abs,
            "partial_fraction": trade.tp_rules.partial_fraction,
            "move_be_after_tp1": trade.tp_rules.move_be_after_tp1,
        },
        "risk_pct_effective": trade.risk_pct_effective,
        "lot_size": trade.lot_size,
        "entry_price": trade.entry_price,
        "tp1_price": trade.tp1_price,
        "tp2_price": trade.tp2_price,
        "entry_bar_ts": _dt(trade.entry_bar_ts),
        "tp1_hit": trade.tp1_hit,
        "initial_sl_distance": trade.initial_sl_distance,
        "remaining_fraction": trade.remaining_fraction,
        "realized_pnl_amount": trade.realized_pnl_amount,
        "realized_pnl_r": trade.realized_pnl_r,
        "entry_trading_day": _date(trade.entry_trading_day),
        "last_seen_trading_day": _date(trade.last_seen_trading_day),
        "trading_days_since_entry": trade.trading_days_since_entry,
        "settlement_release_day": _date(trade.settlement_release_day),
    }


def trade_from_dict(data: dict[str, Any] | None) -> OpenTrade | None:
    if data is None:
        return None
    rules = data["tp_rules"]
    return OpenTrade(
        local_id=data["local_id"],
        symbol=data["symbol"],
        strategy=StrategyName(data["strategy"]),
        direction=Direction(data["direction"]),
        status=OrderStatus(data["status"]),
        sl=data["sl"],
        tp_rules=TPRules(
            kind=rules["kind"],
            tp1_r=rules["tp1_r"],
            tp2_r=rules["tp2_r"],
            tp1_abs=rules["tp1_abs"],
            partial_fraction=rules["partial_fraction"],
            move_be_after_tp1=rules["move_be_after_tp1"],
        ),
        risk_pct_effective=data["risk_pct_effective"],
        lot_size=data["lot_size"],
        entry_price=data["entry_price"],
        tp1_price=data["tp1_price"],
        tp2_price=data["tp2_price"],
        entry_bar_ts=_parse_dt(data["entry_bar_ts"]),
        tp1_hit=data["tp1_hit"],
        initial_sl_distance=data["initial_sl_distance"],
        remaining_fraction=data["remaining_fraction"],
        realized_pnl_amount=data["realized_pnl_amount"],
        realized_pnl_r=data["realized_pnl_r"],
        entry_trading_day=_parse_date(data["entry_trading_day"]),
        last_seen_trading_day=_parse_date(data["last_seen_trading_day"]),
        trading_days_since_entry=data["trading_days_since_entry"],
        settlement_release_day=_parse_date(data["settlement_release_day"]),
    )


def dump_symbol_state(
    breakout_state: BreakoutState,
    trade: OpenTrade | None,
    trade_db_id: int | None,
    cursor: datetime,
    balance: float,
    equity: float,
) -> str:
    return json.dumps(
        {
            "version": STATE_VERSION,
            "breakout_state": breakout_state_to_dict(breakout_state),
            "trade": trade_to_dict(trade),
            "trade_db_id": trade_db_id,
            "cursor": cursor.isoformat(),
            "balance": balance,
            "equity": equity,
        },
        separators=(",", ":"),
    )


class SymbolStateSnapshot:
    """Parsed `strategy_state` payload for one symbol."""

    def __init__(self, data: dict[str, Any]) -> None:
        self.breakout_state = breakout_state_from_dict(data["breakout_state"])
        self.trade = trade_from_dict(data["trade"])
        self.trade_db_id = data["trade_db_id"]
        cursor = _parse_dt(data["cursor"])
        assert cursor is not None
        self.cursor = cursor
        self.balance = float(data["balance"])
        self.equity = float(data["equity"])


def load_symbol_state(state_json: str) -> SymbolStateSnapshot | None:
    """Returns None for a payload written by a different (unknown) version — the runner
    then refuses to resume rather than resuming with a half-understood state."""
    data = json.loads(state_json)
    if data.get("version") != STATE_VERSION:
        return None
    return SymbolStateSnapshot(data)

"""Shared strategy types. Strategies are pure functions: (context, cross-bar state) ->
(Optional[Signal], new_state). Cross-bar state lets the breakout-retest state machine
evaluate every bar regardless of regime (plan requirement — state persists across bars)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from bot.core.types import Direction


@dataclass(frozen=True)
class BreakoutState:
    """Persisted across bars (plan: `breakout_state` DB table). status NONE means no
    pending breakout; AWAITING_RETEST means a breakout fired and we're waiting up to
    RETEST_MAX_BARS (C6) for price to retest the broken level."""

    status: str = "NONE"  # "NONE" | "AWAITING_RETEST"
    direction: Direction | None = None
    range_high: float | None = None
    range_low: float | None = None
    breakout_bar_ts: datetime | None = None
    bars_waited: int = 0

    @staticmethod
    def initial() -> BreakoutState:
        return BreakoutState()

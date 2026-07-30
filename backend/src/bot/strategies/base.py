"""Shared strategy types. Strategies are pure functions: (context, cross-bar state) ->
(Optional[Signal], new_state). Cross-bar state lets the breakout-retest state machine
evaluate every bar regardless of regime (plan requirement — state persists across bars)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from bot.core.types import Direction


@dataclass(frozen=True)
class BreakoutState:
    """Persisted across bars (plan: `breakout_state` DB table).

    BRB (docs/spec_v2.md §2, plan "Nâng cấp Breakout -> BRB") is a 4-phase machine:

    - NONE: no pending breakout.
    - AWAITING_PEAK: breakout-1 fired, watching for Peak1 (impulse extreme) within
      `peak_max_bars`.
    - AWAITING_RETEST: Peak1 confirmed, waiting up to `retest_confirm_max_bars` for price
      to retest the broken level (with confirmation candle).
    - AWAITING_BREAKOUT2: retest confirmed, waiting up to `breakout2_max_bars` for close
      to break Peak1 -> emits the Signal.

    `require_second_breakout=false` (config) collapses this back to the v1.2 machine:
    NONE -> AWAITING_RETEST -> signal at retest (peak1/retest fields unused).

    `bars_waited` counts bars spent in the CURRENT phase only -- reset to 0 on every
    phase transition, so each phase gets its own fresh budget."""

    status: str = "NONE"  # NONE | AWAITING_PEAK | AWAITING_RETEST | AWAITING_BREAKOUT2
    direction: Direction | None = None
    range_high: float | None = None
    range_low: float | None = None
    breakout_bar_ts: datetime | None = None
    bars_waited: int = 0
    peak1: float | None = None
    retest_low: float | None = None
    retest_high: float | None = None

    @staticmethod
    def initial() -> BreakoutState:
        return BreakoutState()

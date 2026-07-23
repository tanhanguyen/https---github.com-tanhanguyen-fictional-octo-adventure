"""Hold rules by timeframe (user decision 2026-07-18 đợt 2, plan 07 §4).

The rule the user chose, verbatim:

  * **TF <= H1** (15m, 1H — forex/crypto move fast): a position is NOT held over the
    weekend and NOT held longer than 8 hours. The 8h time stop applies **even after
    TP1** — a deliberate deviation from C5, which disables the time stop once TP1 is
    hit (recorded in docs/decisions.md).
  * **TF > H1** (4H, 1D, 1W): weekend holds are fine and the time stop is off. This is
    the same conclusion the VN profile reached independently (plan 05).

Weekend-flat only makes sense where the market actually closes: forex has a weekend
gap, crypto perpetuals trade 24/7 and therefore have no window to flatten into. The
patch is a plain config patch, so the rule lives in the versioned config snapshot of
the run rather than in engine code, and a backtest can reproduce a live run exactly by
using the same snapshot.

Precedence (`live_effective_config`): global config < SYMBOL_TYPE profile < hold rules
< per-symbol `overrides`. Hold rules sit under `overrides` so a deliberate per-symbol
override still wins ("vẫn override thủ công được").
"""

from __future__ import annotations

from typing import Any

from bot.core.timeframes import tf_rank

#: Everything at or below 1H is "fast" for hold-rule purposes.
_FAST_TF_MAX_RANK = tf_rank("1H")

#: The 8h cap the user asked for (kept as hours, not bars: the point is wall-clock
#: exposure, and `bars` would silently re-scale it per timeframe).
HOLD_MAX_HOURS = 8.0


def is_fast_timeframe(timeframe: str) -> bool:
    return tf_rank(timeframe) <= _FAST_TF_MAX_RANK


def hold_rule_patch(timeframe: str, symbol_type: str) -> dict[str, Any]:
    """Config patch implementing the hold rules for one symbol."""
    if is_fast_timeframe(timeframe):
        return {
            "execution": {"weekend_flat": symbol_type == "FOREX"},
            "filters": {
                "time_stop": {
                    "enabled": True,
                    "bars": None,
                    "hours": HOLD_MAX_HOURS,
                    "after_tp1": True,
                }
            },
        }
    return {
        "execution": {"weekend_flat": False},
        "filters": {"time_stop": {"enabled": False}},
    }

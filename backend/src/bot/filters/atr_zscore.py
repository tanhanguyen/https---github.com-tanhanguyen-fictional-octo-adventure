"""Filter 5 — ATR Z-score (MODIFIER, and a gate: z < z_off_low turns the bot OFF).

§6.4 / §8 step 4. Boundary: z == z_mid_low (1.0) falls into the strict `>` else branch
-> sl_scale_normal (documented plan boundary case)."""

from __future__ import annotations

from bot.core.types import FilterKind, FilterResult
from bot.filters.base import FilterContext, disabled_result, is_nan, warmup_result

FILTER_ID = "atr_zscore"


def evaluate(ctx: FilterContext) -> FilterResult:
    cfg = ctx.config.filters.atr_zscore
    if not cfg.enabled:
        result = disabled_result(FILTER_ID, FilterKind.MODIFIER)
        result.values = {
            "sl_scale": 1.0,
            "allow_breakout": True,
            "allow_mean_reversion": True,
        }
        return result

    z = ctx.atr_zscore.iloc[-1]
    if is_nan(z):
        result = warmup_result(FILTER_ID, FilterKind.MODIFIER)
        result.values = {
            "sl_scale": 1.0,
            "allow_breakout": True,
            "allow_mean_reversion": True,
        }
        return result

    if z < cfg.z_off_low:
        return FilterResult(
            id=FILTER_ID,
            kind=FilterKind.MODIFIER,
            enabled=True,
            evaluated=True,
            passed=False,
            blocking=True,
            values={
                "z": z,
                "sl_scale": 1.0,
                "allow_breakout": False,
                "allow_mean_reversion": False,
            },
            detail=f"Z={z:.2f} < {cfg.z_off_low} -> bot off (too quiet)",
        )
    if z > cfg.z_breakout_only:
        sl_scale = cfg.sl_scale_high
        allow_mr = False
    elif z > cfg.z_mid_low:
        sl_scale = cfg.sl_scale_mid
        allow_mr = True
    else:
        sl_scale = cfg.sl_scale_normal
        allow_mr = True

    return FilterResult(
        id=FILTER_ID,
        kind=FilterKind.MODIFIER,
        enabled=True,
        evaluated=True,
        passed=True,
        blocking=False,
        values={
            "z": z,
            "sl_scale": sl_scale,
            "allow_breakout": True,
            "allow_mean_reversion": allow_mr,
        },
        detail=f"Z={z:.2f} sl_scale={sl_scale}",
    )

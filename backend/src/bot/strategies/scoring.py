"""BRB confirmation scoring matrix (docs/spec_v2.md §5). Pure — reads only from
`FilterContext` series + `Signal`, no I/O. Computed at the breakout-2 (signal) bar.

Threshold is a RATIO (`total / max_available`), not an absolute score: volume (A3) is
excluded from `max_available` when the symbol has no volume data (FOREX), so an
absolute 8/12 cutoff would be unreachable there while VN (A3 included) would be judged
on the same 12-point scale -- the ratio keeps both asset classes comparable."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from bot.core.types import Direction, Signal
from bot.filters.base import FilterContext
from bot.indicators.candle import body_size, is_engulfing, is_pin_bar

A1_POINTS = 2
A2_POINTS = 1
A3_POINTS = 2
A4_POINTS = 1
B1_POINTS = 2
B2_POINTS = 2
B3_POINTS = 1
C1_POINTS = 1

A1_BODY_MULT = 2.0
A2_WICK_BODY_MULT = 0.3
A3_VOLUME_MULT = 1.8
A4_DEPTH_PCT = 0.003
B1_BODY_MAX_POSITION = 1.0 / 3.0  # "thân gần mép": body within the outer third
BODY_SMA_PERIOD = 10

#: spec_v2 §5 middle tier: a 6-7/12 score may still be taken "nếu A1+B1+C1 ≥ 5". A1(2) +
#: B1(2) + C1(1) sums to exactly 5, so the condition is really "all three of the strong-body
#: breakout, the pin-bar retest and the RSI confirmation passed". Absolute points, not a
#: ratio: A1/B1/C1 never include volume, so the sum is already comparable across FOREX
#: (max 10) and VN (max 12).
CORE_REQUIRED_POINTS = 5


@dataclass
class ScoringResult:
    total: int
    max_available: int
    breakdown: dict[str, bool] = field(default_factory=dict)
    #: Points earned among A1/B1/C1 only -- the middle tier's escape hatch.
    core_total: int = 0

    @property
    def ratio(self) -> float:
        return self.total / self.max_available if self.max_available > 0 else 0.0


@dataclass(frozen=True)
class ScoringGate:
    """Verdict of the 3-tier threshold (spec_v2 §5). `tier` is for the decision detail:
    "primary" (>= threshold), "secondary" (middle band rescued by A1+B1+C1), "below"."""

    passed: bool
    tier: str


def gate(
    result: ScoringResult,
    primary_ratio: float,
    secondary_ratio: float,
    core_required: int = CORE_REQUIRED_POINTS,
) -> ScoringGate:
    """spec_v2 §5 thresholds, on the ratio scale (see module docstring for why ratio):
    `>= primary_ratio` enters; `[secondary_ratio, primary_ratio)` enters only when
    `core_total >= core_required`; below `secondary_ratio` is always cancelled."""
    if result.ratio >= primary_ratio:
        return ScoringGate(passed=True, tier="primary")
    if result.ratio >= secondary_ratio and result.core_total >= core_required:
        return ScoringGate(passed=True, tier="secondary")
    return ScoringGate(passed=False, tier="below")


def _retest_candle(
    ctx: FilterContext, retest_bars_ago: int
) -> tuple[float, float, float, float] | None:
    idx = -(1 + retest_bars_ago)
    if -idx > len(ctx.close):
        return None
    open_ = float(ctx.open_.iloc[idx])
    high = float(ctx.high.iloc[idx])
    low = float(ctx.low.iloc[idx])
    close = float(ctx.close.iloc[idx])
    if any(math.isnan(v) for v in (open_, high, low, close)):
        return None
    return open_, high, low, close


def _prev_candle(ctx: FilterContext, idx: int) -> tuple[float, float] | None:
    """open/close of the candle immediately before position `idx`."""
    prev_idx = idx - 1
    if -prev_idx > len(ctx.close):
        return None
    prev_open = float(ctx.open_.iloc[prev_idx])
    prev_close = float(ctx.close.iloc[prev_idx])
    if math.isnan(prev_open) or math.isnan(prev_close):
        return None
    return prev_open, prev_close


def compute_score(ctx: FilterContext, signal: Signal) -> ScoringResult:
    assert signal.peak1 is not None
    side = signal.direction.value
    total = 0
    max_available = 0
    breakdown: dict[str, bool] = {}

    open_ = float(ctx.open_.iloc[-1])
    high = float(ctx.high.iloc[-1])
    low = float(ctx.low.iloc[-1])
    close = float(ctx.close.iloc[-1])

    # A1: breakout body > 2x SMA(body, 10)
    body_series = (ctx.close - ctx.open_).abs()
    body_sma = body_series.rolling(window=BODY_SMA_PERIOD, min_periods=BODY_SMA_PERIOD).mean()
    body_sma_val = float(body_sma.iloc[-1])
    max_available += A1_POINTS
    a1 = not math.isnan(body_sma_val) and body_size(open_, close) > A1_BODY_MULT * body_sma_val
    breakdown["A1_body"] = a1
    if a1:
        total += A1_POINTS

    # A2: breakout wick (same side as direction) < 0.3 x body
    max_available += A2_POINTS
    body = body_size(open_, close)
    if signal.direction == Direction.BUY:
        same_side_wick = high - max(open_, close)
    else:
        same_side_wick = min(open_, close) - low
    a2 = body > 0 and same_side_wick < A2_WICK_BODY_MULT * body
    breakdown["A2_wick"] = a2
    if a2:
        total += A2_POINTS

    # A3: volume (only counted when the symbol actually tracks volume, e.g. VN stocks)
    if ctx.config.filters.volume.enabled:
        max_available += A3_POINTS
        vol = float(ctx.volume.iloc[-1])
        vol_ma = float(ctx.volume_ma.iloc[-1])
        a3 = not (math.isnan(vol) or math.isnan(vol_ma)) and vol > A3_VOLUME_MULT * vol_ma
        breakdown["A3_volume"] = a3
        if a3:
            total += A3_POINTS
    else:
        breakdown["A3_volume"] = False

    # A4: breakout depth >= 0.3% of price, measured from the RANGE level (spec_v2 §5:
    # "Đóng cửa cách Range ≥ 0.3%"). Measuring from peak1 instead made this criterion
    # dead: the breakout-2 bar has by definition only just crossed peak1, so the distance
    # is ~0 and A4 never scored -- one point permanently off a 10-point FOREX scale.
    max_available += A4_POINTS
    level = signal.range_high if signal.direction == Direction.BUY else signal.range_low
    if level is None or close == 0:
        a4 = False
    else:
        a4 = abs(close - level) / close >= A4_DEPTH_PCT
    breakdown["A4_depth"] = a4
    if a4:
        total += A4_POINTS

    retest_bars_ago = signal.retest_bars_ago
    retest_candle = _retest_candle(ctx, retest_bars_ago) if retest_bars_ago is not None else None

    # B1: pin bar at retest -- wick > 2x body AND "thân gần mép" (spec_v2 §5). The body
    # position is what keeps B1 a genuinely stronger criterion than B3 rather than a
    # nested restatement of it (a 2.0x wick always satisfies B3's 1.5x, so the two stack
    # by design -- but only B1 requires the body to sit at the rejecting edge).
    max_available += B1_POINTS
    b1 = False
    if retest_candle is not None:
        r_open, r_high, r_low, r_close = retest_candle
        b1 = is_pin_bar(
            r_open,
            r_high,
            r_low,
            r_close,
            side,
            wick_body_mult=2.0,
            body_max_position=B1_BODY_MAX_POSITION,
        )
    breakdown["B1_pin_bar"] = b1
    if b1:
        total += B1_POINTS

    # B2: engulfing at retest
    max_available += B2_POINTS
    b2 = False
    if retest_candle is not None and retest_bars_ago is not None:
        r_open, _r_high, _r_low, r_close = retest_candle
        prev = _prev_candle(ctx, -(1 + retest_bars_ago))
        if prev is not None:
            b2 = is_engulfing(prev[0], prev[1], r_open, r_close, side)
    breakdown["B2_engulfing"] = b2
    if b2:
        total += B2_POINTS

    # B3: long wick at retest (weaker threshold than B1's pin bar)
    max_available += B3_POINTS
    b3 = False
    if retest_candle is not None:
        r_open, r_high, r_low, r_close = retest_candle
        b3 = is_pin_bar(r_open, r_high, r_low, r_close, side, wick_body_mult=1.5)
    breakdown["B3_long_wick"] = b3
    if b3:
        total += B3_POINTS

    # C1: RSI confirmation
    max_available += C1_POINTS
    rsi_val = float(ctx.rsi.iloc[-1])
    c1 = (not math.isnan(rsi_val)) and (
        rsi_val > 55.0 if signal.direction == Direction.BUY else rsi_val < 45.0
    )
    breakdown["C1_rsi"] = c1
    if c1:
        total += C1_POINTS

    core_total = (A1_POINTS if a1 else 0) + (B1_POINTS if b1 else 0) + (C1_POINTS if c1 else 0)
    return ScoringResult(
        total=total,
        max_available=max_available,
        breakdown=breakdown,
        core_total=core_total,
    )

"""BRB confirmation scoring matrix (docs/spec_v2.md §5)."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import pytest

from bot.config.loader import load_default_config
from bot.core.types import Direction, Signal, StrategyName
from bot.filters.base import FilterContext
from bot.indicators.atr import atr
from bot.indicators.ema import ema
from bot.indicators.rsi import rsi
from bot.strategies import scoring

N = 15


def _ctx(
    *,
    retest_row: tuple[float, float, float, float] = (1.1040, 1.1045, 1.1000, 1.1038),
    prev_retest_row: tuple[float, float] = (1.1000, 1.1000),
    breakout_row: tuple[float, float, float, float] = (1.1038, 1.1090, 1.1035, 1.1085),
    rsi_close: list[float] | None = None,
    volume_enabled: bool = False,
    volume: float = 1000.0,
    volume_ma: float = 1000.0,
) -> FilterContext:
    """15 flat bars, with the retest candle at index -3 (retest_bars_ago=2, so the
    prev-retest candle for engulfing lives at index -4) and the breakout-2 candle at
    index -1."""
    cfg = load_default_config()
    cfg.filters.volume.enabled = volume_enabled

    # Alternating small bodies (~0.0004) so SMA(body, 10) lands at a realistic non-zero
    # baseline -- a flat all-doji series would make even a tiny breakout body "> 2x SMA".
    opens = [1.1000] * N
    highs = [1.1010] * N
    lows = [1.0990] * N
    closes = [1.1000 + (0.0004 if i % 2 == 0 else -0.0004) for i in range(N)]
    vols = [volume_ma] * N
    vol_ma_series = [volume_ma] * N

    opens[-4], closes[-4] = prev_retest_row
    opens[-3], highs[-3], lows[-3], closes[-3] = retest_row
    opens[-1], highs[-1], lows[-1], closes[-1] = breakout_row
    vols[-1] = volume

    close = pd.Series(rsi_close if rsi_close is not None else closes)
    high = pd.Series(highs)
    low = pd.Series(lows)
    open_ = pd.Series(opens)
    vol = pd.Series(vols)

    return FilterContext(
        config=cfg,
        now=datetime(2024, 6, 3, tzinfo=timezone.utc),
        symbol="EURUSD",
        open_=open_,
        high=high,
        low=low,
        close=close,
        volume=vol,
        ema_fast_close=ema(close, 34),
        ema_fast_high=ema(high, 34),
        ema_fast_low=ema(low, 34),
        ema_slow_close=ema(close, 89),
        adx=pd.Series([float("nan")] * N),
        er=pd.Series([float("nan")] * N),
        rsi=rsi(close, 14),
        atr14=atr(high, low, close, 14),
        atr5=atr(high, low, close, 5),
        atr_zscore=pd.Series([float("nan")] * N),
        volume_ma=pd.Series(vol_ma_series),
    )


def _signal(**overrides) -> Signal:
    base = dict(
        direction=Direction.BUY,
        strategy=StrategyName.BREAKOUT,
        signal_bar_ts=datetime(2024, 6, 3, tzinfo=timezone.utc),
        range_high=1.1010,
        range_low=1.0990,
        peak1=1.1075,
        retest_low=1.1000,
        retest_high=1.1045,
        retest_bars_ago=2,
    )
    base.update(overrides)
    return Signal(**base)


def test_a1_body_scores_when_breakout_body_more_than_2x_sma():
    ctx = _ctx()
    result = scoring.compute_score(ctx, _signal())
    assert result.breakdown["A1_body"] is True  # body 0.0047 vs flat-bar SMA body ~0


def test_a1_body_does_not_score_on_a_small_body():
    ctx = _ctx(breakout_row=(1.1038, 1.1041, 1.1037, 1.1039))
    result = scoring.compute_score(ctx, _signal())
    assert result.breakdown["A1_body"] is False


def test_a2_small_same_side_wick_scores():
    # BUY: upper wick (high - max(open,close)) small vs body -> A2 True
    ctx = _ctx(breakout_row=(1.1038, 1.1086, 1.1035, 1.1085))
    result = scoring.compute_score(ctx, _signal())
    assert result.breakdown["A2_wick"] is True


def test_a2_large_same_side_wick_fails():
    ctx = _ctx(breakout_row=(1.1038, 1.1150, 1.1035, 1.1045))  # huge upper wick, small body
    result = scoring.compute_score(ctx, _signal())
    assert result.breakdown["A2_wick"] is False


def test_a3_excluded_from_max_available_when_volume_filter_disabled():
    """FOREX default (filters.volume.enabled=False, D3): A3 must not count toward
    max_available at all, so the ratio threshold stays reachable."""
    ctx = _ctx(volume_enabled=False)
    result = scoring.compute_score(ctx, _signal())
    assert result.breakdown["A3_volume"] is False
    assert result.max_available == 10  # 12 - A3's 2 points


def test_a3_included_and_scores_when_volume_filter_enabled():
    ctx = _ctx(volume_enabled=True, volume=2000.0, volume_ma=1000.0)
    result = scoring.compute_score(ctx, _signal())
    assert result.max_available == 12
    assert result.breakdown["A3_volume"] is True


def test_a4_depth_scores_when_close_is_far_enough_past_the_range():
    ctx = _ctx(breakout_row=(1.1038, 1.1200, 1.1035, 1.1150))
    result = scoring.compute_score(ctx, _signal(range_high=1.1010, peak1=1.1075))
    assert result.breakdown["A4_depth"] is True


def test_a4_depth_fails_when_close_is_within_0_3pct_of_the_range():
    """spec_v2 §5 A4 measures depth from the RANGE, not from peak1 -- measured from peak1
    the breakout-2 close is always ~0 away (it just crossed it), so A4 never scored."""
    ctx = _ctx(breakout_row=(1.1038, 1.1090, 1.1035, 1.1076))
    result = scoring.compute_score(ctx, _signal(range_high=1.1060, peak1=1.1070))
    assert result.breakdown["A4_depth"] is False


def test_a4_depth_uses_range_low_for_sell():
    ctx = _ctx(breakout_row=(1.1038, 1.1042, 1.0900, 1.0910))
    result = scoring.compute_score(
        ctx, _signal(direction=Direction.SELL, range_low=1.1000, peak1=1.0930)
    )
    assert result.breakdown["A4_depth"] is True


def test_b1_pin_bar_fails_when_body_sits_mid_range():
    """spec_v2 B1 also requires "thân gần mép" -- without it B1 was a nested restatement
    of B3 (a 2x wick trivially clears B3's 1.5x)."""
    # lower wick 0.0030 > 2x body 0.0004, but the body sits in the middle of the range
    ctx = _ctx(retest_row=(1.1020, 1.1060, 1.0990, 1.1024))
    result = scoring.compute_score(ctx, _signal())
    assert result.breakdown["B3_long_wick"] is True
    assert result.breakdown["B1_pin_bar"] is False


def test_b1_pin_bar_at_retest_scores():
    # long lower wick (0.0038) vs tiny body (0.0002)
    ctx = _ctx(retest_row=(1.1040, 1.1045, 1.1000, 1.1038))
    result = scoring.compute_score(ctx, _signal())
    assert result.breakdown["B1_pin_bar"] is True


def test_b1_pin_bar_fails_on_a_normal_candle():
    ctx = _ctx(retest_row=(1.1030, 1.1045, 1.1025, 1.1040))
    result = scoring.compute_score(ctx, _signal())
    assert result.breakdown["B1_pin_bar"] is False


def test_b2_engulfing_at_retest_scores():
    # prev candle small red body [1.1010 -> 1.1005]; retest candle engulfs it fully
    ctx = _ctx(prev_retest_row=(1.1010, 1.1005), retest_row=(1.1000, 1.1020, 1.0995, 1.1015))
    result = scoring.compute_score(ctx, _signal())
    assert result.breakdown["B2_engulfing"] is True


def test_b2_engulfing_fails_when_body_does_not_engulf_prev():
    ctx = _ctx(prev_retest_row=(1.1010, 1.1005), retest_row=(1.1008, 1.1012, 1.1006, 1.1009))
    result = scoring.compute_score(ctx, _signal())
    assert result.breakdown["B2_engulfing"] is False


def test_c1_rsi_confirms_buy_above_55():
    rsi_close = [100.0 + 0.05 * i for i in range(N)]  # steady uptrend -> RSI > 55
    ctx = _ctx(rsi_close=rsi_close)
    result = scoring.compute_score(ctx, _signal(direction=Direction.BUY))
    assert result.breakdown["C1_rsi"] is True


def test_c1_rsi_rejects_buy_when_oversold():
    rsi_close = [100.0 - 0.05 * i for i in range(N)]  # downtrend -> RSI < 45
    ctx = _ctx(rsi_close=rsi_close)
    result = scoring.compute_score(ctx, _signal(direction=Direction.BUY))
    assert result.breakdown["C1_rsi"] is False


def test_ratio_is_total_over_max_available():
    ctx = _ctx()
    result = scoring.compute_score(ctx, _signal())
    assert result.ratio == pytest.approx(result.total / result.max_available)


def test_core_total_counts_only_a1_b1_c1():
    ctx = _ctx()
    result = scoring.compute_score(ctx, _signal())
    expected = (
        (scoring.A1_POINTS if result.breakdown["A1_body"] else 0)
        + (scoring.B1_POINTS if result.breakdown["B1_pin_bar"] else 0)
        + (scoring.C1_POINTS if result.breakdown["C1_rsi"] else 0)
    )
    assert result.core_total == expected
    assert scoring.CORE_REQUIRED_POINTS == scoring.A1_POINTS + scoring.B1_POINTS + scoring.C1_POINTS


def _result(total: int, core_total: int, max_available: int = 10) -> scoring.ScoringResult:
    return scoring.ScoringResult(
        total=total, max_available=max_available, breakdown={}, core_total=core_total
    )


def test_gate_primary_tier_passes_on_score_alone():
    verdict = scoring.gate(_result(total=8, core_total=0), 0.66, 0.5)
    assert verdict.passed is True
    assert verdict.tier == "primary"


def test_gate_middle_tier_passes_only_with_all_core_criteria():
    """spec_v2 §5: "6-7/12 → có thể xem xét thêm nếu A1+B1+C1 ≥ 5". A1+B1+C1 sums to
    exactly 5, so the escape hatch requires all three."""
    rescued = scoring.gate(_result(total=6, core_total=5), 0.66, 0.5)
    assert rescued.passed is True
    assert rescued.tier == "secondary"

    # same score, one core criterion missing (C1's single point) -> no rescue
    blocked = scoring.gate(_result(total=6, core_total=4), 0.66, 0.5)
    assert blocked.passed is False
    assert blocked.tier == "below"


def test_gate_below_secondary_is_never_rescued():
    """spec_v2 §5: "< 6/12 → ❌ hủy" is unconditional -- core criteria cannot save it."""
    verdict = scoring.gate(_result(total=4, core_total=5), 0.66, 0.5)
    assert verdict.passed is False
    assert verdict.tier == "below"

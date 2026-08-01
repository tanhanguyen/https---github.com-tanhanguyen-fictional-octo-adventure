"""Plan 11 §2 "Chống leak tuyệt đối" — the window boundary tests.

Two things must hold, and they pull in opposite directions:
  (a) a window's feed must contain NO bar at/after the window end, on ANY timeframe
      (the resampled 4H/1D frames are the sneaky path: one 4H row can carry four 1H
      bars from the other side of the cut);
  (b) a window's feed MUST contain bars from before the window start, or the indicators
      enter the first decision un-warmed — and those warmup bars must all be <= the cut.
"""

from __future__ import annotations

import pandas as pd
import pytest

from bot.core.errors import ConfigError
from bot.core.timeframes import warmup_bars_required
from bot.data.resample import build_all_timeframes
from bot.research.walkforward import degradation
from bot.research.windows import bar_count, build_windows, to_utc, window_frames


def _frames(n_15m: int = 4 * 24 * 400) -> dict[str, pd.DataFrame]:
    """A tidy synthetic 15m series (no gaps) resampled the way a dataset bundle is."""
    index = pd.date_range("2020-01-01", periods=n_15m, freq="15min", tz="UTC")
    price = pd.Series(range(n_15m), dtype=float) / 1000.0 + 100.0
    df = pd.DataFrame(
        {
            "open": price.values,
            "high": price.values + 0.05,
            "low": price.values - 0.05,
            "close": price.values,
            "volume": 1000.0,
        },
        index=index,
    )
    df.index.name = "open_ts"
    return build_all_timeframes(df, "America/New_York", "17:00")


# --------------------------------------------------------------- window schedule


def test_windows_are_contiguous_and_oos_starts_where_is_ends() -> None:
    windows = build_windows(
        to_utc("2020-01-01"), to_utc("2024-01-01"), is_months=12, oos_months=3, step_months=3
    )
    assert [w.index for w in windows] == list(range(len(windows)))
    for w in windows:
        assert w.oos_from == w.is_to
        assert w.is_to == w.is_from + pd.DateOffset(months=12)
        assert w.oos_to == w.oos_from + pd.DateOffset(months=3)
    for a, b in zip(windows, windows[1:], strict=False):
        assert b.is_from == a.is_from + pd.DateOffset(months=3)


def test_a_trailing_partial_window_is_dropped_not_shortened() -> None:
    """Reporting one window on 1 month of OOS next to others on 3 would silently make
    the degradation column incomparable."""
    windows = build_windows(
        to_utc("2020-01-01"), to_utc("2021-05-15"), is_months=12, oos_months=3, step_months=3
    )
    assert len(windows) == 1
    assert windows[-1].oos_to <= to_utc("2021-05-15")


def test_no_complete_window_is_an_error_not_an_empty_report() -> None:
    with pytest.raises(ConfigError, match="no complete IS"):
        build_windows(
            to_utc("2020-01-01"), to_utc("2020-06-01"), is_months=12, oos_months=3, step_months=3
        )


def test_naive_timestamps_are_read_as_utc() -> None:
    assert to_utc("2020-01-01").isoformat() == "2020-01-01T00:00:00+00:00"
    assert to_utc("2020-01-01T05:00:00+02:00").isoformat() == "2020-01-01T03:00:00+00:00"


# ------------------------------------------------------------------- no leak (a)


def test_no_timeframe_carries_a_bar_from_past_the_cut() -> None:
    frames = _frames()
    cut = to_utc("2020-03-01")
    sliced = window_frames(frames, "1H", to_utc("2020-02-01"), cut)
    for tf, df in sliced.frames.items():
        assert len(df) > 0, tf
        assert df.index.max() < cut, f"{tf} leaks a bar at/after the cut"


def test_the_is_and_oos_slices_of_one_window_share_no_bar() -> None:
    frames = _frames()
    is_slice = window_frames(frames, "1H", to_utc("2020-02-01"), to_utc("2020-03-01"))
    oos_slice = window_frames(frames, "1H", to_utc("2020-03-01"), to_utc("2020-04-01"))
    # The OOS feed DOES contain IS bars -- that is its warmup, and it is legitimate
    # (backward-looking). What must never happen is the reverse.
    decided_oos = oos_slice.frames["1H"].loc[oos_slice.frames["1H"].index >= is_slice.end]
    assert len(decided_oos) > 0
    assert is_slice.frames["1H"].index.intersection(decided_oos.index).empty


# ------------------------------------------------------------------ warmup (b)


def test_warmup_bars_come_from_before_the_cursor_and_only_from_before() -> None:
    frames = _frames()
    start, end = to_utc("2020-02-01"), to_utc("2020-03-01")
    sliced = window_frames(frames, "1H", start, end)

    base = sliced.frames["1H"]
    warmup = base.loc[base.index < sliced.cursor]
    assert len(warmup) == warmup_bars_required("1H") or sliced.warm_from == frames["1H"].index[0]
    assert warmup.index.max() < to_utc(sliced.cursor)
    assert sliced.cursor == to_utc(start).to_pydatetime()


def test_the_cursor_is_the_first_bar_at_or_after_the_requested_start() -> None:
    frames = _frames()
    # 10:17 is mid-bar: the cursor must round FORWARD to 11:00, never back to 10:00
    # (starting on a bar that opened before the window would decide on window-external data).
    sliced = window_frames(frames, "1H", to_utc("2020-02-03T10:17:00"), to_utc("2020-03-01"))
    assert to_utc(sliced.cursor) == to_utc("2020-02-03T11:00:00")


def test_bar_count_counts_only_the_decided_bars_not_the_warmup() -> None:
    frames = _frames()
    start, end = to_utc("2020-02-01"), to_utc("2020-02-08")
    sliced = window_frames(frames, "1H", start, end)
    expected = int(((frames["1H"].index >= start) & (frames["1H"].index < end)).sum())
    assert bar_count(sliced.frames, "1H", sliced.cursor) == expected
    assert len(sliced.frames["1H"]) > expected  # warmup really is in the feed


def test_a_window_starting_past_the_data_is_an_error() -> None:
    with pytest.raises(ConfigError, match="after the last bar"):
        window_frames(_frames(), "1H", to_utc("2030-01-01"), to_utc("2031-01-01"))


def test_an_empty_window_is_an_error() -> None:
    frames = _frames()
    with pytest.raises(ConfigError, match="empty window"):
        window_frames(frames, "1H", to_utc("2020-02-01T00:10"), to_utc("2020-02-01T00:20"))


# ----------------------------------------------------------------- degradation


@pytest.mark.parametrize(
    ("is_metric", "oos_metric", "expected"),
    [
        (2.0, 1.0, -0.5),
        (2.0, 2.0, 0.0),
        (1.0, 1.5, 0.5),
        (None, 1.0, None),
        (1.0, None, None),
        (0.0, 1.0, None),
    ],
)
def test_degradation(is_metric, oos_metric, expected) -> None:
    assert degradation(is_metric, oos_metric) == expected

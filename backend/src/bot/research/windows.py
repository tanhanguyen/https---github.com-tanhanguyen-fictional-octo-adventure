"""Window slicing for sweeps and walk-forward — where the no-leak guarantee lives.

Two separate guarantees, both tested (`tests/unit/test_walkforward_windows.py`):

1. **No future bar in a window's feed.** `window_frames` drops every bar whose OPEN is
   at or after the window's end, on every timeframe. An IS run therefore cannot see a
   single OOS bar, not even through the resampled higher timeframe: a 4H frame row is
   only kept when it opens before the cut, and `Feed` (C11) additionally hides it until
   it has closed — which for a boundary-straddling bar never happens inside the window.

2. **Warmup looks BACKWARD only.** A window starts its decisions at `start`, but the
   indicators need history. The feed therefore also carries `warmup_bars_required(tf)`
   bars from BEFORE `start` and the runner's cursor is set to `start`, so warmup uses
   only bars <= the cut (the same spirit as `test_no_lookahead`). Warmup is counted in
   BARS, not in calendar time: real forex data has weekend gaps, so a fixed timedelta
   would silently under-warm the indicators near a holiday.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import pandas as pd

from bot.core.errors import ConfigError
from bot.core.timeframes import warmup_bars_required


@dataclass(frozen=True)
class Window:
    """A contiguous [start, end) slice of a dataset, in bar-OPEN timestamps."""

    index: int
    is_from: pd.Timestamp
    is_to: pd.Timestamp
    oos_from: pd.Timestamp
    oos_to: pd.Timestamp

    def phase(self, phase: str) -> tuple[pd.Timestamp, pd.Timestamp]:
        return (self.is_from, self.is_to) if phase == "is" else (self.oos_from, self.oos_to)


def to_utc(value: str | datetime | pd.Timestamp) -> pd.Timestamp:
    """Parse to a tz-aware UTC Timestamp. Naive input is READ as UTC (dataset frames are
    tz-aware UTC), never as local time — a machine-dependent window would make a sweep
    non-reproducible."""
    ts = pd.Timestamp(value)
    return ts.tz_localize(timezone.utc) if ts.tz is None else ts.tz_convert(timezone.utc)


@dataclass(frozen=True)
class SlicedWindow:
    frames: dict[str, pd.DataFrame]
    #: First bar the runner DECIDES on (everything before it is warmup only).
    cursor: datetime
    #: First bar present in the feed at all — the left edge of the warmup.
    warm_from: pd.Timestamp
    end: pd.Timestamp


def slice_between(
    frames: dict[str, pd.DataFrame], warm_from: pd.Timestamp, end: pd.Timestamp
) -> dict[str, pd.DataFrame]:
    """`[warm_from, end)` on every timeframe, by bar-OPEN timestamp."""
    return {tf: df.loc[(df.index >= warm_from) & (df.index < end)] for tf, df in frames.items()}


def window_frames(
    frames: dict[str, pd.DataFrame], primary_tf: str, start: pd.Timestamp, end: pd.Timestamp
) -> SlicedWindow:
    """Slice every timeframe to `[warmup_start, end)` and return the runner's cursor.

    The cursor is the first primary-tf bar opening at/after `start`: the runner decides
    from there on, while everything before it exists only to warm the indicators."""
    base = frames.get(primary_tf)
    if base is None or len(base) == 0:
        raise ConfigError(f"dataset has no bars on timeframe {primary_tf!r}")
    idx = base.index
    pos = int(idx.searchsorted(start, side="left"))
    if pos >= len(idx):
        raise ConfigError(
            f"window start {start.isoformat()} is after the last bar "
            f"({idx[-1].isoformat()}) of this dataset"
        )
    cursor = idx[pos]
    if cursor >= end:
        raise ConfigError(
            f"empty window: first bar at/after {start.isoformat()} is {cursor.isoformat()}, "
            f"which is already past the window end {end.isoformat()}"
        )
    warm_from = idx[max(0, pos - warmup_bars_required(primary_tf))]

    sliced = slice_between(frames, warm_from, end)
    if len(sliced[primary_tf]) == 0:  # pragma: no cover - guarded by the checks above
        raise ConfigError("window slice is empty")
    return SlicedWindow(
        frames=sliced, cursor=cursor.to_pydatetime(), warm_from=warm_from, end=end
    )


def bar_count(frames: dict[str, pd.DataFrame], primary_tf: str, cursor: datetime) -> int:
    """How many primary-tf bars a run over `frames` will actually process (warmup bars
    are in the feed but never decided on) — the input to the cost guard's estimate."""
    idx = frames[primary_tf].index
    return int((idx >= to_utc(cursor)).sum())


def add_months(ts: pd.Timestamp, months: int) -> pd.Timestamp:
    """Calendar-month arithmetic that clamps to the end of a short month (31 Jan + 1 =
    28/29 Feb), so a walk-forward schedule never skips or duplicates a day."""
    return ts + pd.DateOffset(months=months)


def build_windows(
    data_from: pd.Timestamp,
    data_to: pd.Timestamp,
    is_months: int,
    oos_months: int,
    step_months: int,
) -> list[Window]:
    """Consecutive (IS, OOS) windows: OOS starts exactly where IS ends, and the whole
    pair must fit inside the data — a partial trailing OOS window is DROPPED rather
    than reported on fewer months than every other window."""
    windows: list[Window] = []
    is_from = data_from
    while True:
        is_to = add_months(is_from, is_months)
        oos_to = add_months(is_to, oos_months)
        if oos_to > data_to:
            break
        windows.append(
            Window(
                index=len(windows),
                is_from=is_from,
                is_to=is_to,
                oos_from=is_to,
                oos_to=oos_to,
            )
        )
        is_from = add_months(is_from, step_months)
    if not windows:
        raise ConfigError(
            f"no complete IS({is_months}m)+OOS({oos_months}m) window fits in "
            f"{data_from.date()}..{data_to.date()} — shorten the windows or widen the range"
        )
    return windows

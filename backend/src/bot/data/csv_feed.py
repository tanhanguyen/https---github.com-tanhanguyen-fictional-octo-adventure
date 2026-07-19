"""Load a real (non-synthetic) OHLCV CSV at its native timeframe and build all
higher timeframes via the same resample pipeline used for synthetic data, so MTF
consistency is structural either way (plan 02)."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pandas as pd

from bot.core.errors import FeedError
from bot.core.timeframes import tf_duration
from bot.data.resample import build_all_timeframes

_REQUIRED_COLUMNS = ["open", "high", "low", "close", "volume"]


def _validate_grid(df: pd.DataFrame, tf: str) -> None:
    if tf == "1D":
        times = {(ts.hour, ts.minute, ts.second) for ts in df.index}
        if len(times) > 1:
            first_time = next(iter(times))
            bad = next(ts for ts in df.index if (ts.hour, ts.minute, ts.second) != first_time)
            raise FeedError(
                f"1D grid violation at {bad.isoformat()}: daily bars must share one "
                "fixed time-of-day (gaps for weekends/holidays are fine, drift is not)"
            )
        return

    dur = tf_duration(tf)
    first = df.index[0]
    for ts in df.index:
        if (ts - first) % dur != timedelta(0):
            raise FeedError(
                f"{tf} grid violation at {ts.isoformat()}: not aligned to a {dur} grid "
                f"anchored at {first.isoformat()}"
            )


def _validate(df: pd.DataFrame, tf: str) -> None:
    if not df.index.is_unique:
        dup = df.index[df.index.duplicated()][0]
        raise FeedError(f"duplicate open_ts at {dup.isoformat()}")
    if not df.index.is_monotonic_increasing:
        raise FeedError("open_ts index must be strictly increasing")

    if df[_REQUIRED_COLUMNS].isna().any().any():
        bad_rows = df.index[df[_REQUIRED_COLUMNS].isna().any(axis=1)]
        raise FeedError(f"NaN value at open_ts={bad_rows[0].isoformat()}")

    hi_bad = df.index[df["high"] < df[["open", "close"]].max(axis=1)]
    if len(hi_bad) > 0:
        raise FeedError(f"high < max(open,close) at open_ts={hi_bad[0].isoformat()}")
    lo_bad = df.index[df["low"] > df[["open", "close"]].min(axis=1)]
    if len(lo_bad) > 0:
        raise FeedError(f"low > min(open,close) at open_ts={lo_bad[0].isoformat()}")

    _validate_grid(df, tf)


def load_csv(
    path: Path,
    tf: str,
    rollover_tz: str = "America/New_York",
    rollover_time: str = "17:00",
) -> dict[str, pd.DataFrame]:
    df = pd.read_csv(path, index_col="open_ts", parse_dates=["open_ts"])
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    else:
        df.index = df.index.tz_convert("UTC")
    df = df[_REQUIRED_COLUMNS].sort_index()
    _validate(df, tf)
    return build_all_timeframes(df, rollover_tz, rollover_time, base_tf=tf)


def load_csv_15m(
    path: Path, rollover_tz: str = "America/New_York", rollover_time: str = "17:00"
) -> dict[str, pd.DataFrame]:
    return load_csv(path, "15m", rollover_tz, rollover_time)

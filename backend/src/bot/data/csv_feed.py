"""Load a real (non-synthetic) 15m OHLCV CSV and build all timeframes via the same
resample pipeline used for synthetic data, so MTF consistency is structural either way."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from bot.data.resample import build_all_timeframes


def load_csv_15m(
    path: Path, rollover_tz: str = "America/New_York", rollover_time: str = "17:00"
) -> dict[str, pd.DataFrame]:
    df = pd.read_csv(path, index_col="open_ts", parse_dates=["open_ts"])
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    else:
        df.index = df.index.tz_convert("UTC")
    df = df[["open", "high", "low", "close", "volume"]].sort_index()
    return build_all_timeframes(df, rollover_tz, rollover_time)

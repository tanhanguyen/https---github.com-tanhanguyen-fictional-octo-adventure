"""Resample OHLCV frames upward: 15m -> 1H -> 4H (plain UTC-hour buckets) and
1H -> 1D -> 1W anchored at the trading-day rollover (C3, 17:00 America/New_York)."""

from __future__ import annotations

from datetime import date, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from bot.core.timeframes import trading_day, trading_day_start_local

_AGG = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}


def resample_fixed(df: pd.DataFrame, freq: str) -> pd.DataFrame:
    """Plain UTC-epoch-aligned resample, used for 15m->1H and 1H->4H."""
    out = df.resample(freq, label="left", closed="left").agg(_AGG)
    return out.dropna(subset=["open", "high", "low", "close"])


def resample_trading_day(
    df: pd.DataFrame, rollover_tz: str = "America/New_York", rollover_time: str = "17:00"
) -> pd.DataFrame:
    """1H -> 1D, anchored to the trading-day rollover (C3) so the daily candle and the
    trading day share one boundary."""
    tz = ZoneInfo(rollover_tz)

    days = [trading_day(ts.to_pydatetime(), rollover_tz, rollover_time) for ts in df.index]
    tmp = df.copy()
    tmp["_day"] = days

    rows = []
    for day, g in tmp.groupby("_day"):
        g = g.sort_index()
        open_local = trading_day_start_local(day, rollover_time).replace(tzinfo=tz)
        open_ts = open_local.astimezone(ZoneInfo("UTC"))
        rows.append(
            {
                "open_ts": open_ts,
                "open": g["open"].iloc[0],
                "high": g["high"].max(),
                "low": g["low"].min(),
                "close": g["close"].iloc[-1],
                "volume": g["volume"].sum(),
            }
        )
    out = pd.DataFrame(rows).set_index("open_ts").sort_index()
    out.index.name = "open_ts"
    return out


def resample_trading_week(
    df1d: pd.DataFrame, rollover_tz: str = "America/New_York", rollover_time: str = "17:00"
) -> pd.DataFrame:
    """1D -> 1W, Monday-trading-day anchored (same rollover convention, C3)."""
    tz = ZoneInfo(rollover_tz)

    def week_start(ts: pd.Timestamp) -> date:
        local_day = trading_day(ts.to_pydatetime(), rollover_tz, rollover_time)
        return local_day - timedelta(days=local_day.weekday())

    tmp = df1d.copy()
    tmp["_week"] = [week_start(ts) for ts in df1d.index]

    rows = []
    for wk, g in tmp.groupby("_week"):
        g = g.sort_index()
        open_local = trading_day_start_local(wk, rollover_time).replace(tzinfo=tz)
        open_ts = open_local.astimezone(ZoneInfo("UTC"))
        rows.append(
            {
                "open_ts": open_ts,
                "open": g["open"].iloc[0],
                "high": g["high"].max(),
                "low": g["low"].min(),
                "close": g["close"].iloc[-1],
                "volume": g["volume"].sum(),
            }
        )
    out = pd.DataFrame(rows).set_index("open_ts").sort_index()
    out.index.name = "open_ts"
    return out


def build_all_timeframes(
    df_base: pd.DataFrame,
    rollover_tz: str = "America/New_York",
    rollover_time: str = "17:00",
    base_tf: str = "15m",
) -> dict[str, pd.DataFrame]:
    """Resample UPWARD only from `base_tf` (plan 02: real CSV data may already start
    at 1H/4H/1D — e.g. VN derivatives have no 15m — so lower frames simply don't
    exist then). `base_tf="15m"` (the default) reproduces the original synthetic
    pipeline byte-for-byte, so every existing positional call site is unaffected."""
    frames: dict[str, pd.DataFrame] = {base_tf: df_base}
    if base_tf == "15m":
        frames["1H"] = resample_fixed(df_base, "1h")
        frames["4H"] = resample_fixed(frames["1H"], "4h")
        frames["1D"] = resample_trading_day(frames["1H"], rollover_tz, rollover_time)
    elif base_tf == "1H":
        frames["4H"] = resample_fixed(df_base, "4h")
        frames["1D"] = resample_trading_day(df_base, rollover_tz, rollover_time)
    elif base_tf == "4H":
        frames["1D"] = resample_trading_day(df_base, rollover_tz, rollover_time)
    if "1D" in frames:
        frames["1W"] = resample_trading_week(frames["1D"], rollover_tz, rollover_time)
    return frames

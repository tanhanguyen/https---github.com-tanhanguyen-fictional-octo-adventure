"""Resample OHLCV frames upward: 15m -> 1H -> 4H (plain UTC-hour buckets) and
1H -> 1D -> 1W anchored at the trading-day rollover (C3, 17:00 America/New_York)."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from bot.core.timeframes import trading_day

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
    hh, mm = (int(p) for p in rollover_time.split(":"))

    days = [trading_day(ts.to_pydatetime(), rollover_tz, rollover_time) for ts in df.index]
    tmp = df.copy()
    tmp["_day"] = days

    rows = []
    for day, g in tmp.groupby("_day"):
        g = g.sort_index()
        open_local = datetime.combine(day - timedelta(days=1), time(hh, mm), tzinfo=tz)
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
    hh, mm = (int(p) for p in rollover_time.split(":"))

    def week_start(ts: pd.Timestamp) -> date:
        local_day = trading_day(ts.to_pydatetime(), rollover_tz, rollover_time)
        return local_day - timedelta(days=local_day.weekday())

    tmp = df1d.copy()
    tmp["_week"] = [week_start(ts) for ts in df1d.index]

    rows = []
    for wk, g in tmp.groupby("_week"):
        g = g.sort_index()
        open_local = datetime.combine(wk - timedelta(days=1), time(hh, mm), tzinfo=tz)
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
    df15: pd.DataFrame, rollover_tz: str = "America/New_York", rollover_time: str = "17:00"
) -> dict[str, pd.DataFrame]:
    df1h = resample_fixed(df15, "1h")
    df4h = resample_fixed(df1h, "4h")
    df1d = resample_trading_day(df1h, rollover_tz, rollover_time)
    df1w = resample_trading_week(df1d, rollover_tz, rollover_time)
    return {"15m": df15, "1H": df1h, "4H": df4h, "1D": df1d, "1W": df1w}

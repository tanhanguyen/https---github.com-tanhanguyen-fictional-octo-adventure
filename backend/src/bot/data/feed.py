"""Feed: the single point where C11 (no-lookahead) is enforced.

A bar on timeframe `tf` opening at `open_ts` is only visible once
`open_ts + tf_duration(tf) <= end_ts` (the bar has fully closed). `bars()` filters on
this BEFORE `.tail(n)` -- filtering after would leak a still-forming bar into view.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import pandas as pd

from bot.core.timeframes import tf_duration
from bot.core.types import Bar


@dataclass
class Feed:
    frames: dict[str, pd.DataFrame]  # tf -> DataFrame indexed by open_ts (tz-aware UTC)

    def bars(self, tf: str, end_ts: datetime, n: int) -> pd.DataFrame:
        """Return the last `n` CLOSED bars on `tf` as of `end_ts` (C11)."""
        df = self.frames[tf]
        dur = tf_duration(tf)
        closed_mask = (df.index + dur) <= end_ts
        visible = df.loc[closed_mask]
        return visible.tail(n)

    def bar_at(self, tf: str, open_ts: datetime) -> Bar | None:
        """The (possibly still-forming) bar that OPENS at `open_ts` -- used by the order
        engine to process the live bar. Not subject to the C11 filter (the engine is
        explicitly looking at the bar currently in progress)."""
        df = self.frames[tf]
        if open_ts not in df.index:
            return None
        row = df.loc[open_ts]
        dur = tf_duration(tf)
        return Bar(
            open_ts=open_ts,
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=float(row["volume"]),
            close_ts=open_ts + dur,
        )

    def next_open_after(self, tf: str, ts: datetime) -> datetime | None:
        df = self.frames[tf]
        candidates = df.index[df.index >= ts]
        if len(candidates) == 0:
            return None
        result: datetime = candidates[0].to_pydatetime()
        return result

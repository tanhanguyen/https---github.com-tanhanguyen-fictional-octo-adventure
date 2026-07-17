"""Injected clock — the only source of time inside the engine (C10).

datetime.now()/time.time() are banned in engine code; test_no_wallclock greps for them.
"""

from __future__ import annotations

from datetime import datetime, timezone


class Clock:
    """Simulation clock. Always tz-aware UTC."""

    def __init__(self, start: datetime) -> None:
        if start.tzinfo is None:
            raise ValueError("Clock requires tz-aware datetimes")
        self._now = start.astimezone(timezone.utc)

    @property
    def now(self) -> datetime:
        return self._now

    def set(self, ts: datetime) -> None:
        if ts.tzinfo is None:
            raise ValueError("Clock requires tz-aware datetimes")
        ts = ts.astimezone(timezone.utc)
        if ts < self._now:
            raise ValueError(f"Clock cannot go backwards: {ts} < {self._now}")
        self._now = ts

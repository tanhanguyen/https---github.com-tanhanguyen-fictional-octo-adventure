"""The ONE place real wall-clock time enters the process (plan 07).

Invariant #3 (`test_no_wallclock`) bans `datetime.now()` inside engine/filters/
strategies/indicators. Live trading obviously needs to know what time it really is, so
the live layer takes a `NowFn` injected from here: `bot.engine.live_runner` never calls
`datetime.now()` itself, it calls the function it was handed. That keeps the ban intact
(and makes every live test run on a deterministic fake clock instead of real time).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

#: A source of "now", always tz-aware UTC.
NowFn = Callable[[], datetime]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)

"""LiveFeed — real-time OHLCV from Binance USDⓈ-M Futures (plan 07 §1).

Venue decision (user, 2026-07-18): crypto is futures-only and Binance USDⓈ-M Futures is
the first venue. `GET /fapi/v1/klines` is public (no API key), returns UTC-anchored bars,
and testnet speaks the identical schema — so demo and live differ only by base URL.

Two hard rules this module exists to enforce:

1. **Only CLOSED bars leave this module.** A kline whose `open_ts + tf_duration` is
   still in the future is dropped, no matter what the venue returns. This is the same
   C11 rule the replay `Feed` enforces, applied one layer earlier.
2. **Network trouble degrades, it never crashes.** Every request is retried with
   exponential backoff + jitter; when the retries are exhausted the feed raises
   `LiveFeedError`, which the runner turns into a `degraded` status + alert and then
   keeps looping.

The output is a plain DataFrame indexed by `open_ts` (tz-aware UTC) with OHLCV columns —
byte-identical in shape to what the CSV loader produces, so it flows through
`resample.build_all_timeframes` like every other source.
"""

from __future__ import annotations

import json
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd

from bot.core.errors import FeedError
from bot.core.timeframes import tf_duration, warmup_bars_required

#: Public market-data hosts. Both expose the same `/fapi/v1/klines` schema.
BINANCE_FUTURES_MAINNET = "https://fapi.binance.com"
BINANCE_FUTURES_TESTNET = "https://testnet.binancefuture.com"

#: Venue cap on `limit` for one klines request; more than this needs pagination.
MAX_KLINES_PER_REQUEST = 1500

#: Our timeframe vocabulary -> Binance's `interval` parameter.
INTERVAL_BY_TIMEFRAME: dict[str, str] = {
    "15m": "15m",
    "1H": "1h",
    "4H": "4h",
    "1D": "1d",
    "1W": "1w",
}

OHLCV_COLUMNS = ["open", "high", "low", "close", "volume"]

#: (url, timeout_seconds) -> raw response body. Injected so tests never touch a socket.
HttpGetFn = Callable[[str, float], bytes]


class LiveFeedError(FeedError):
    """The venue could not be reached (or answered nonsense) after every retry."""


def urllib_get(url: str, timeout: float) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "trading-bot/0.1"})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        body: bytes = response.read()
    return body


def empty_frame() -> pd.DataFrame:
    """An empty OHLCV frame with the right dtypes and a tz-aware UTC index, so callers
    can concat/compare against it without special-casing the no-data path."""
    index = pd.DatetimeIndex([], tz="UTC", name="open_ts")
    return pd.DataFrame({c: pd.Series(dtype="float64") for c in OHLCV_COLUMNS}, index=index)


def _to_ms(ts: datetime) -> int:
    return int(ts.timestamp() * 1000)


@dataclass
class RetryPolicy:
    """Exponential backoff with full jitter. `rng` is injected so a test can assert on
    exact sleep durations without waiting for them."""

    max_attempts: int = 5
    base_delay: float = 1.0
    max_delay: float = 30.0
    rng: random.Random = field(default_factory=random.Random)

    def delay_for(self, attempt: int) -> float:
        """`attempt` is 1-based: the pause AFTER the attempt-th failure."""
        ceiling = min(self.max_delay, self.base_delay * (2 ** (attempt - 1)))
        return self.rng.uniform(0.0, ceiling)


class BinanceFuturesFeed:
    """Polls one symbol/timeframe of Binance USDⓈ-M Futures klines."""

    def __init__(
        self,
        symbol: str,
        timeframe: str,
        base_url: str = BINANCE_FUTURES_MAINNET,
        http_get: HttpGetFn | None = None,
        retry: RetryPolicy | None = None,
        timeout: float = 10.0,
        sleep_fn: Callable[[float], None] | None = None,
    ) -> None:
        if timeframe not in INTERVAL_BY_TIMEFRAME:
            raise FeedError(
                f"timeframe {timeframe!r} has no Binance interval "
                f"(known: {sorted(INTERVAL_BY_TIMEFRAME)})"
            )
        self.symbol = symbol
        self.timeframe = timeframe
        self.interval = INTERVAL_BY_TIMEFRAME[timeframe]
        self.base_url = base_url.rstrip("/")
        self.http_get = http_get if http_get is not None else urllib_get
        self.retry = retry or RetryPolicy()
        self.timeout = timeout
        self.sleep_fn = sleep_fn if sleep_fn is not None else time.sleep
        self.duration = tf_duration(timeframe)

    # ------------------------------------------------------------------ HTTP
    def _url(self, limit: int, end_time: datetime | None) -> str:
        params: dict[str, Any] = {
            "symbol": self.symbol,
            "interval": self.interval,
            "limit": min(limit, MAX_KLINES_PER_REQUEST),
        }
        if end_time is not None:
            params["endTime"] = _to_ms(end_time)
        return f"{self.base_url}/fapi/v1/klines?{urllib.parse.urlencode(params)}"

    def _request(self, url: str) -> list[list[Any]]:
        """One request, retried with backoff + jitter. Raises LiveFeedError when the
        attempts are exhausted -- the caller degrades, it does not die."""
        last_error: Exception | None = None
        for attempt in range(1, self.retry.max_attempts + 1):
            try:
                payload = json.loads(self.http_get(url, self.timeout).decode("utf-8"))
            except (urllib.error.URLError, OSError, ValueError, TimeoutError) as exc:
                last_error = exc
            else:
                if isinstance(payload, dict):
                    # Binance reports errors as {"code": -1121, "msg": "Invalid symbol."}
                    last_error = LiveFeedError(f"venue error: {payload}")
                elif not isinstance(payload, list):
                    last_error = LiveFeedError(f"unexpected klines payload: {payload!r}")
                else:
                    return payload
            if attempt < self.retry.max_attempts:
                self.sleep_fn(self.retry.delay_for(attempt))
        raise LiveFeedError(
            f"{self.symbol} {self.interval}: {self.retry.max_attempts} attempts failed "
            f"({last_error})"
        ) from last_error

    # ------------------------------------------------------------------ parse
    def _to_frame(self, klines: list[list[Any]], now: datetime) -> pd.DataFrame:
        """Rule 1: a bar is only emitted once `open_ts + tf_duration <= now`.

        The venue's own `close_time` is `open_time + interval - 1ms`, which would make
        the very last bar look closed one millisecond early; deriving the close from
        `open_ts` keeps the live definition of "closed" identical to the engine's."""
        rows = []
        for k in klines:
            open_ts = datetime.fromtimestamp(int(k[0]) / 1000, tz=timezone.utc)
            if open_ts + self.duration > now:
                continue  # still forming
            rows.append(
                {
                    "open_ts": open_ts,
                    "open": float(k[1]),
                    "high": float(k[2]),
                    "low": float(k[3]),
                    "close": float(k[4]),
                    "volume": float(k[5]),
                }
            )
        if not rows:
            return empty_frame()
        df = pd.DataFrame(rows).set_index("open_ts").sort_index()
        df.index.name = "open_ts"
        return df[~df.index.duplicated(keep="last")]

    # ------------------------------------------------------------------ public
    def fetch_closed(
        self, now: datetime, limit: int = 500, end_time: datetime | None = None
    ) -> pd.DataFrame:
        """The most recent closed bars as of `now` (at most `limit` from the venue)."""
        return self._to_frame(self._request(self._url(limit, end_time)), now)

    def backfill(self, now: datetime, bars: int | None = None) -> pd.DataFrame:
        """Load enough history to warm up every indicator before the first live bar.

        Pages BACKWARDS with `endTime` because the venue caps a single response at
        `MAX_KLINES_PER_REQUEST` and a 1D run needs ~2100 bars (300 weekly bars of
        EMA89 warmup — see `warmup_bars_required`)."""
        target = bars if bars is not None else warmup_bars_required(self.timeframe)
        collected: list[pd.DataFrame] = []
        total = 0
        cursor: datetime | None = None
        # Bound the paging so a venue that keeps answering with the same page (or with
        # a single bar) cannot spin forever.
        max_pages = max(1, -(-target // MAX_KLINES_PER_REQUEST) + 2)
        for _ in range(max_pages):
            page = self.fetch_closed(now, limit=MAX_KLINES_PER_REQUEST, end_time=cursor)
            if page.empty:
                break
            collected.append(page)
            total += len(page)
            earliest = page.index[0].to_pydatetime()
            if total >= target:
                break
            next_cursor = earliest - timedelta(milliseconds=1)
            if cursor is not None and next_cursor >= cursor:
                break  # not making progress
            cursor = next_cursor
        if not collected:
            return empty_frame()
        df = pd.concat(collected).sort_index()
        df = df[~df.index.duplicated(keep="last")]
        return df.tail(target)

    def next_close_after(self, now: datetime) -> datetime:
        """The next instant at which a bar of this timeframe closes.

        Bars are anchored to the UTC epoch (15m/1H/4H/1D all divide a day evenly, and
        Binance anchors weeklies to Monday 00:00 UTC), so the next close is just the
        next multiple of the duration strictly after `now`."""
        step = int(self.duration.total_seconds())
        epoch_anchor = datetime(1970, 1, 5, tzinfo=timezone.utc)  # a Monday, for 1W
        elapsed = int((now - epoch_anchor).total_seconds())
        return epoch_anchor + timedelta(seconds=(elapsed // step + 1) * step)

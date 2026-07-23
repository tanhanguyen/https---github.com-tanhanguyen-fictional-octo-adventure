"""DNSE OpenAPI market data — real OHLC for Vietnamese spot (HOSE/HNX/UPCOM) and
derivatives (VN30F), replacing the "VN has no candle source" hole left by plan 07.

Source of truth: <https://developers.dnse.com.vn/docs/dnse/get-ohlc-history> (REST
history) and <https://developers.dnse.com.vn/docs/guide/market-data/connect> (the
`ohlc_closed` WebSocket channel). Both serve `type = STOCK | DERIVATIVE | INDEX`, so one
module covers cổ phiếu, phái sinh **and** the market indices.

Why REST polling and not the WebSocket
--------------------------------------
Plan 07 decision #4 already chose polling for the crypto feed, and the reasons hold here
verbatim: the engine only ever consumes CLOSED bars on a >= 15m grid (VN profile forces
1D), polling has far fewer failure states than a stateful socket, and — decisively — the
same `BarSource` protocol keeps `test_live_matches_replay` meaningful. The `ohlc_closed`
WebSocket channel is a latency optimisation for a later plan; the protocol is written
down in docs/decisions.md so it is a small job when it is wanted.

Three unit traps this module exists to absorb
---------------------------------------------
1. **Stock prices come in THOUSANDS of VND.** DNSE quotes HPG as `24.35`, meaning
   24,350 VND. Every instrument spec, fixture and golden dataset in this repo is in
   whole VND (`hpg_1d_sample.csv` opens at 27000.0), and `pip = 1.0 VND`. So STOCK bars
   are scaled by `STOCK_PRICE_SCALE`. DERIVATIVE (index points, e.g. 1881.2) and INDEX
   are already in the engine's units and are NOT scaled.
2. **Daily bars are re-anchored to the VN session open (09:00 ICT = 02:00 UTC).** That
   is the convention every VN dataset in this repo uses, and the one plan 05 §9 relies
   on when it says a D1 bar's `close_ts` lands at 09:00 ICT of the NEXT session. The
   normalisation goes through the ICT *calendar date*, so it is idempotent whichever
   midnight the venue happens to stamp (00:00 ICT, 00:00 UTC or 09:00 ICT all reduce to
   the same trading date).
3. **Closed means `open_ts + tf_duration <= now`,** exactly as in `live_feed` and in the
   replay `Feed` (C11). For a VN D1 bar that means today's candle is only visible at
   09:00 ICT tomorrow — which is precisely when the next bar opens, so the D6 fill
   ("decide at close[-1], fill at open[+1]") lands on that session's open. Do not
   "fix" this to 14:45 ICT: it would make live diverge from every backtest ever run.

Auth (REST): HMAC-SHA256 over an HTTP-Signature signing string, see `sign_request`.
Credentials come from `DNSE_API_KEY` / `DNSE_API_SECRET` and are never logged.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from bot.core.errors import ConfigError, FeedError
from bot.core.timeframes import tf_duration, warmup_bars_required
from bot.data.live_feed import (
    LiveFeedError,
    RetryPolicy,
    empty_frame,
)

#: Public REST host for market data (docs: "Base URL https://openapi.dnse.com.vn").
DNSE_OPENAPI_BASE = "https://openapi.dnse.com.vn"

#: Path of the OHLC history endpoint. Kept separate from the base URL because it is also
#: the `(request-target)` half of the signing string.
OHLC_PATH = "/price/ohlc"

#: Asia/Ho_Chi_Minh has no DST, but naming the zone beats hardcoding +07.
VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")

#: HOSE/HNX continuous session opens 09:00 local. Every VN daily bar in this repo is
#: keyed to this instant (see module docstring trap #2).
VN_SESSION_OPEN_HOUR = 9

#: DNSE quotes cổ phiếu in thousands of VND; the engine works in whole VND.
STOCK_PRICE_SCALE = 1000.0

#: Our timeframe vocabulary -> DNSE `resolution`. DNSE offers 1/3/5/15/30/1H/1D/1W —
#: there is NO 4H, which is fine: the VN profile forces 1D (plan 05 decision #2) and a
#: 4H bar over a 4.5h session was deliberately never defined.
RESOLUTION_BY_TIMEFRAME: dict[str, str] = {
    "15m": "15",
    "1H": "1H",
    "1D": "1D",
    "1W": "1W",
}

#: `SYMBOL_TYPE` (D11) -> DNSE `type` query parameter.
MARKET_TYPE_BY_SYMBOL_TYPE: dict[str, str] = {
    "STOCK_VN_CASH": "STOCK",
    "STOCK_VN_DERIV": "DERIVATIVE",
}

VALID_MARKET_TYPES = ("STOCK", "DERIVATIVE", "INDEX")

#: How much MORE calendar time than bar-time a window of N bars spans, per timeframe.
#: The VN market trades ~4h45 a day, 5 days a week, minus public holidays — asking for
#: `N * tf_duration` of calendar time would come back with a small fraction of N bars.
#: These are deliberate over-estimates; the pager simply stops early when it has enough.
CALENDAR_STRETCH: dict[str, float] = {
    "15m": 8.0,
    "1H": 8.0,
    "1D": 1.7,
    "1W": 1.1,
}

#: Bars requested per REST call while paging backwards through history.
CHUNK_BARS = 400

#: Absolute floor for the backfill pager: VN30F index futures listed in Aug 2017 and no
#: strategy here looks further back, so this only bounds a pathological loop.
EARLIEST_HISTORY = datetime(2015, 1, 1, tzinfo=timezone.utc)

#: (url, headers, timeout) -> raw response body. Injected so tests never touch a socket.
HttpGetFn = Callable[[str, Mapping[str, str], float], bytes]


class DnseFeedError(LiveFeedError):
    """DNSE could not be reached, or answered something that is not an OHLC payload."""


def urllib_get(url: str, headers: Mapping[str, str], timeout: float) -> bytes:
    request = urllib.request.Request(url, headers=dict(headers))
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        body: bytes = response.read()
    return body


# --------------------------------------------------------------------------- auth
@dataclass(frozen=True)
class DnseCredentials:
    """API key/secret pair issued by DNSE when the OpenAPI service is registered.

    Held as a frozen dataclass rather than read from `os.environ` at the call site so a
    test can pass fake values, and so `__repr__` of a feed never drags the secret into a
    log line (the feed keeps the credentials private and never formats them)."""

    api_key: str
    api_secret: str

    @staticmethod
    def from_env(env: Mapping[str, str] | None = None) -> DnseCredentials:
        environ = env if env is not None else os.environ
        key = environ.get("DNSE_API_KEY", "").strip()
        secret = environ.get("DNSE_API_SECRET", "").strip()
        if not key or not secret:
            raise ConfigError(
                "DNSE market data needs DNSE_API_KEY and DNSE_API_SECRET in the "
                "environment (register at https://developers.dnse.com.vn). Fail-closed: "
                "a VN live run refuses to start rather than run blind."
            )
        return DnseCredentials(api_key=key, api_secret=secret)


def signing_string(method: str, path: str, date_header: str, nonce: str) -> str:
    """The exact bytes DNSE signs (docs "Xác thực" → step 1).

    Line order and lower-casing are load-bearing; the docs call out that getting either
    wrong is an immediate reject:

        (request-target): get /accounts
        date: Fri, 15 May 2026 07:11:30 +0000
        nonce: c9a8f88b472c9721fde161e0d89df8cc

    The documented example carries NO query string, so by default only the path is
    signed. `DNSE_SIGN_QUERY=1` switches to the draft-cavage reading (path + query) in
    case the live endpoint disagrees — see the "to verify" list in docs/decisions.md.
    """
    return "\n".join(
        [
            f"(request-target): {method.lower()} {path}",
            f"date: {date_header}",
            f"nonce: {nonce}",
        ]
    )


def encode_signature(raw: bytes) -> str:
    """Base64, then URL-encode ONLY the three characters base64 can produce (`+ / =`).
    Not a general quote() call: double-encoding is an explicit doc warning."""
    b64 = base64.b64encode(raw).decode("ascii")
    return b64.replace("+", "%2B").replace("/", "%2F").replace("=", "%3D")


def sign_request(
    credentials: DnseCredentials,
    method: str,
    path: str,
    now: datetime,
    nonce: str | None = None,
    sign_query: bool = False,
    query: str = "",
) -> dict[str, str]:
    """Build the auth headers for one request.

    `Date` must be within ±1 minute of DNSE's clock and the nonce must be fresh, so
    these headers are computed per request and never cached.
    """
    target = f"{path}?{query}" if (sign_query and query) else path
    nonce_value = nonce if nonce is not None else uuid.uuid4().hex
    date_header = format_datetime(now.astimezone(timezone.utc))
    # email.utils renders UTC as "+0000" (RFC 1123 / RFC 5322), matching the doc example.
    message = signing_string(method, target, date_header, nonce_value)
    digest = hmac.new(
        credentials.api_secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256
    ).digest()
    encoded = encode_signature(digest)
    return {
        "X-API-Key": credentials.api_key,
        # The auth guide names the header `Date`; the OHLC endpoint spec names it
        # `X-Aux-Date`. Sending both with the same value satisfies either reading and
        # costs nothing — an extra header is never a rejection reason.
        "Date": date_header,
        "X-Aux-Date": date_header,
        "X-Signature": (
            f'Signature keyId="{credentials.api_key}",algorithm="hmac-sha256",'
            f'headers="(request-target) date",signature="{encoded}",nonce="{nonce_value}"'
        ),
        "Accept": "application/json",
        "User-Agent": "trading-bot/0.1",
    }


# --------------------------------------------------------------------- bar timestamps
def vn_session_open(day: datetime) -> datetime:
    """09:00 Asia/Ho_Chi_Minh on the ICT calendar day containing `day`, as UTC."""
    local = day.astimezone(VN_TZ)
    return local.replace(hour=VN_SESSION_OPEN_HOUR, minute=0, second=0, microsecond=0).astimezone(
        timezone.utc
    )


def normalize_bar_ts(ts: datetime, timeframe: str) -> datetime:
    """Re-key a venue timestamp onto this repo's VN bar grid.

    Intraday bars are already exact instants and pass through untouched. Daily and
    weekly bars are re-anchored to the session open of their ICT trading date (resp. of
    that week's Monday), which makes the result identical whether the venue stamped the
    bar at ICT midnight, UTC midnight or the session open itself.
    """
    if timeframe == "1D":
        return vn_session_open(ts)
    if timeframe == "1W":
        local = ts.astimezone(VN_TZ)
        monday = local - timedelta(days=local.weekday())
        return vn_session_open(monday)
    return ts.astimezone(timezone.utc)


# ------------------------------------------------------------------------- the feed
class DnseOhlcFeed:
    """Polls one symbol/timeframe of DNSE OHLC history. Satisfies `BarSource`.

    `market_type` selects the DNSE `type` parameter and, with it, the price scaling:
    STOCK is quoted in thousands of VND and gets multiplied by `STOCK_PRICE_SCALE`,
    DERIVATIVE and INDEX are already in index points / engine units.
    """

    def __init__(
        self,
        symbol: str,
        timeframe: str,
        market_type: str,
        credentials: DnseCredentials | None = None,
        base_url: str = DNSE_OPENAPI_BASE,
        http_get: HttpGetFn | None = None,
        retry: RetryPolicy | None = None,
        timeout: float = 15.0,
        sleep_fn: Callable[[float], None] | None = None,
        now_header_fn: Callable[[], datetime] | None = None,
        price_scale: float | None = None,
        sign_query: bool | None = None,
    ) -> None:
        if timeframe not in RESOLUTION_BY_TIMEFRAME:
            raise FeedError(
                f"timeframe {timeframe!r} has no DNSE resolution "
                f"(known: {sorted(RESOLUTION_BY_TIMEFRAME)}; DNSE has no 4H bar)"
            )
        if market_type not in VALID_MARKET_TYPES:
            raise FeedError(
                f"market_type {market_type!r} invalid (expected one of {VALID_MARKET_TYPES})"
            )
        self.symbol = symbol
        self.timeframe = timeframe
        self.market_type = market_type
        self.resolution = RESOLUTION_BY_TIMEFRAME[timeframe]
        self.base_url = base_url.rstrip("/")
        self._credentials = credentials if credentials is not None else DnseCredentials.from_env()
        self.http_get = http_get if http_get is not None else urllib_get
        self.retry = retry or RetryPolicy()
        self.timeout = timeout
        self.sleep_fn = sleep_fn if sleep_fn is not None else time.sleep
        # The Date header must track REAL time (±1 minute of DNSE's clock), which is a
        # different concept from the engine's injected `now` — hence a separate hook.
        self.now_header_fn = now_header_fn if now_header_fn is not None else _utc_now
        self.duration = tf_duration(timeframe)
        self.price_scale = (
            price_scale
            if price_scale is not None
            else (STOCK_PRICE_SCALE if market_type == "STOCK" else 1.0)
        )
        self.sign_query = (
            sign_query
            if sign_query is not None
            else os.environ.get("DNSE_SIGN_QUERY", "").strip() in {"1", "true", "yes"}
        )
        self.stretch = CALENDAR_STRETCH[timeframe]

    # ------------------------------------------------------------------ HTTP
    def _query(self, start: datetime, end: datetime) -> str:
        return urllib.parse.urlencode(
            {
                "symbol": self.symbol,
                "type": self.market_type,
                "resolution": self.resolution,
                "from": int(start.timestamp()),
                "to": int(end.timestamp()),
            }
        )

    def _request(self, start: datetime, end: datetime) -> dict[str, Any]:
        """One request, retried with backoff + jitter. Raises `DnseFeedError` once the
        attempts are exhausted — the runner degrades and keeps looping, it does not die.

        Each attempt re-signs: the signature is bound to a Date and a nonce, and DNSE
        rejects a replayed one."""
        query = self._query(start, end)
        url = f"{self.base_url}{OHLC_PATH}?{query}"
        last_error: Exception | None = None
        for attempt in range(1, self.retry.max_attempts + 1):
            headers = sign_request(
                self._credentials,
                "GET",
                OHLC_PATH,
                self.now_header_fn(),
                sign_query=self.sign_query,
                query=query,
            )
            try:
                payload = json.loads(self.http_get(url, headers, self.timeout).decode("utf-8"))
            except (urllib.error.URLError, OSError, ValueError, TimeoutError) as exc:
                last_error = exc
            else:
                if not isinstance(payload, dict):
                    last_error = DnseFeedError(f"unexpected OHLC payload: {payload!r}")
                elif "t" not in payload:
                    # Errors arrive as {"error": ...} / {"message": ...}; either way the
                    # absence of the `t` array is the reliable tell.
                    last_error = DnseFeedError(f"venue error: {payload}")
                else:
                    return payload
            if attempt < self.retry.max_attempts:
                self.sleep_fn(self.retry.delay_for(attempt))
        raise DnseFeedError(
            f"{self.symbol} {self.market_type} {self.resolution}: "
            f"{self.retry.max_attempts} attempts failed ({last_error})"
        ) from last_error

    # ------------------------------------------------------------------ parse
    def _to_frame(self, payload: Mapping[str, Any], now: datetime) -> pd.DataFrame:
        """Columnar `{t,o,h,l,c,v}` -> the same OHLCV frame the CSV loader produces.

        Applies, in order: closed-bar filtering (`open_ts + duration <= now`), grid
        normalisation, and the STOCK thousand-VND scaling.
        """
        times = payload.get("t") or []
        opens = payload.get("o") or []
        highs = payload.get("h") or []
        lows = payload.get("l") or []
        closes = payload.get("c") or []
        volumes = payload.get("v") or []
        lengths = {len(times), len(opens), len(highs), len(lows), len(closes), len(volumes)}
        if len(lengths) > 1:
            raise DnseFeedError(
                f"{self.symbol}: ragged OHLC payload, array lengths {sorted(lengths)}"
            )
        scale = self.price_scale
        rows = []
        for i, raw_ts in enumerate(times):
            open_ts = normalize_bar_ts(
                datetime.fromtimestamp(int(raw_ts), tz=timezone.utc), self.timeframe
            )
            if open_ts + self.duration > now:
                continue  # still forming — rule 3 in the module docstring
            rows.append(
                {
                    "open_ts": open_ts,
                    "open": float(opens[i]) * scale,
                    "high": float(highs[i]) * scale,
                    "low": float(lows[i]) * scale,
                    "close": float(closes[i]) * scale,
                    "volume": float(volumes[i]),
                }
            )
        if not rows:
            return empty_frame()
        df = pd.DataFrame(rows).set_index("open_ts").sort_index()
        df.index.name = "open_ts"
        # Re-anchoring D1/1W can collapse two venue rows onto one grid slot (it never
        # should, but a duplicated bar must not reach the engine): last write wins.
        return df[~df.index.duplicated(keep="last")]

    def _window(self, bars: int, end: datetime) -> datetime:
        """Start of a calendar window expected to contain at least `bars` bars."""
        span = self.duration * bars * self.stretch
        return max(EARLIEST_HISTORY, end - span)

    # ------------------------------------------------------------------ public
    def fetch_closed(
        self, now: datetime, limit: int = 500, end_time: datetime | None = None
    ) -> pd.DataFrame:
        """The most recent closed bars at or before `end_time` (default: `now`)."""
        end = end_time if end_time is not None else now
        start = self._window(limit, end)
        return self._to_frame(self._request(start, end), now).tail(limit)

    def backfill(self, now: datetime, bars: int | None = None) -> pd.DataFrame:
        """Load enough history to warm every indicator before the first live decision.

        Pages BACKWARDS in fixed windows because the endpoint is time-ranged rather than
        count-limited. A short history is NOT an error: VN30F1M has only traded since
        2017, so a 1D run asking for `warmup_bars_required` (2100 bars ≈ 8 years) may
        legitimately get fewer. The engine already answers `wait/warmup` while an
        indicator is still NaN (C12), which is the correct, fail-closed behaviour.
        """
        target = bars if bars is not None else warmup_bars_required(self.timeframe)
        collected: list[pd.DataFrame] = []
        total = 0
        cursor = now
        empty_windows = 0
        max_pages = max(1, -(-target // CHUNK_BARS) + 4)
        for _ in range(max_pages):
            start = self._window(CHUNK_BARS, cursor)
            page = self._to_frame(self._request(start, cursor), now)
            if page.empty:
                # One empty window can just be a holiday stretch; two in a row means we
                # have run off the start of the listing.
                empty_windows += 1
                if empty_windows >= 2 or start <= EARLIEST_HISTORY:
                    break
                cursor = start - self.duration
                continue
            empty_windows = 0
            collected.append(page)
            total += len(page)
            if total >= target or start <= EARLIEST_HISTORY:
                break
            earliest = page.index[0].to_pydatetime()
            next_cursor = min(earliest, start) - self.duration
            if next_cursor >= cursor:
                break  # not making progress
            cursor = next_cursor
        if not collected:
            return empty_frame()
        df = pd.concat(collected).sort_index()
        df = df[~df.index.duplicated(keep="last")]
        return df.tail(target)

    def next_close_after(self, now: datetime) -> datetime:
        """The next instant at which a bar of this timeframe closes.

        Daily/weekly VN bars sit on a 09:00 ICT grid, not the UTC-epoch grid the crypto
        feed uses, so they get their own arithmetic. Intraday frames divide an hour
        evenly and 09:00 ICT is 02:00 UTC, so epoch alignment is exact for them.

        This only schedules WHEN to poll; whether a bar counts as closed is decided in
        `_to_frame`. A wake-up on a weekend or holiday simply finds no new bar.
        """
        if self.timeframe == "1D":
            candidate = vn_session_open(now)
            while candidate <= now:
                candidate = vn_session_open(candidate + timedelta(days=1))
            return candidate
        if self.timeframe == "1W":
            local = now.astimezone(VN_TZ)
            monday = local - timedelta(days=local.weekday())
            candidate = vn_session_open(monday)
            while candidate <= now:
                candidate = vn_session_open(candidate + timedelta(days=7))
            return candidate
        step = int(self.duration.total_seconds())
        elapsed = int(now.timestamp())
        return datetime.fromtimestamp((elapsed // step + 1) * step, tz=timezone.utc)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def market_type_for(symbol_type: str) -> str:
    """DNSE `type` for a D11 `SYMBOL_TYPE`. Raises for non-VN types on purpose: a forex
    or crypto symbol reaching this function is a wiring bug, not a config choice."""
    try:
        return MARKET_TYPE_BY_SYMBOL_TYPE[symbol_type]
    except KeyError:
        raise ConfigError(
            f"symbol_type {symbol_type!r} is not a DNSE market "
            f"(expected one of {sorted(MARKET_TYPE_BY_SYMBOL_TYPE)})"
        ) from None

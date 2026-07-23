"""DNSE OHLC feed: signing, closed-bar filtering, unit scaling, VN bar grid, backfill.

Every test drives an injected `http_get` — nothing here opens a socket, and no test
needs real credentials.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone

import pytest

from bot.core.errors import ConfigError, FeedError
from bot.data.dnse_feed import (
    STOCK_PRICE_SCALE,
    DnseCredentials,
    DnseFeedError,
    DnseOhlcFeed,
    encode_signature,
    market_type_for,
    normalize_bar_ts,
    sign_request,
    signing_string,
    vn_session_open,
)
from bot.data.live_feed import RetryPolicy

UTC = timezone.utc
CREDS = DnseCredentials(api_key="test_key", api_secret="test_secret")

#: 09:00 Asia/Ho_Chi_Minh, the instant every VN daily bar in this repo is keyed to.
SESSION_OPEN_UTC_HOUR = 2


def payload(times: list[int], price: float = 24.0) -> dict[str, object]:
    n = len(times)
    return {
        "t": times,
        "o": [price + i for i in range(n)],
        "h": [price + i + 0.5 for i in range(n)],
        "l": [price + i - 0.5 for i in range(n)],
        "c": [price + i + 0.25 for i in range(n)],
        "v": [1000.0 + i for i in range(n)],
        "nextTime": 0,
    }


def responder(body: object, calls: list[str] | None = None):
    def _get(url: str, headers, timeout: float) -> bytes:
        if calls is not None:
            calls.append(url)
        return json.dumps(body).encode()

    return _get


def daily_ts(*days: int, year: int = 2026, month: int = 7) -> list[int]:
    """Venue timestamps at ICT midnight — deliberately NOT the session open, so the
    normalisation is doing real work in every test that uses this."""
    return [int(datetime(year, month, d, 17, 0, tzinfo=UTC).timestamp() - 24 * 3600) for d in days]


def feed(timeframe: str = "1D", market_type: str = "STOCK", **kwargs) -> DnseOhlcFeed:
    kwargs.setdefault("credentials", CREDS)
    kwargs.setdefault("now_header_fn", lambda: datetime(2026, 7, 23, 3, 0, tzinfo=UTC))
    return DnseOhlcFeed("HPG", timeframe, market_type, **kwargs)


# ------------------------------------------------------------------------ signing
def test_signing_string_matches_documented_layout():
    text = signing_string("GET", "/accounts", "Fri, 15 May 2026 07:11:30 +0000", "abc123")

    assert text == (
        "(request-target): get /accounts\n"
        "date: Fri, 15 May 2026 07:11:30 +0000\n"
        "nonce: abc123"
    )
    assert not text.endswith("\n")  # docs: every line but the last ends with \n


def test_encode_signature_escapes_only_base64_specials():
    raw = bytes([0xFB, 0xFF, 0xFE, 0x00])  # base64 -> "+//+AA==" style output
    encoded = encode_signature(raw)

    assert "+" not in encoded and "/" not in encoded and "=" not in encoded
    assert "%2B" in encoded or "%2F" in encoded
    assert "%252" not in encoded  # never double-encoded


def test_sign_request_signature_is_verifiable_hmac():
    now = datetime(2026, 5, 15, 7, 11, 30, tzinfo=UTC)

    headers = sign_request(CREDS, "GET", "/price/ohlc", now, nonce="n1")

    expected = encode_signature(
        hmac.new(
            b"test_secret",
            signing_string("GET", "/price/ohlc", headers["Date"], "n1").encode(),
            hashlib.sha256,
        ).digest()
    )
    assert f'signature="{expected}"' in headers["X-Signature"]
    assert headers["X-API-Key"] == "test_key"
    assert 'keyId="test_key"' in headers["X-Signature"]
    assert 'headers="(request-target) date"' in headers["X-Signature"]
    assert 'nonce="n1"' in headers["X-Signature"]


def test_date_header_is_rfc1123_utc_and_duplicated_as_x_aux_date():
    now = datetime(2026, 5, 15, 7, 11, 30, tzinfo=UTC)

    headers = sign_request(CREDS, "GET", "/price/ohlc", now, nonce="n1")

    assert headers["Date"] == "Fri, 15 May 2026 07:11:30 +0000"
    # The auth guide names it `Date`, the OHLC endpoint spec names it `X-Aux-Date`.
    assert headers["X-Aux-Date"] == headers["Date"]


def test_sign_query_switches_the_request_target():
    now = datetime(2026, 5, 15, 7, 11, 30, tzinfo=UTC)

    without = sign_request(CREDS, "GET", "/price/ohlc", now, nonce="n", query="symbol=HPG")
    with_query = sign_request(
        CREDS, "GET", "/price/ohlc", now, nonce="n", sign_query=True, query="symbol=HPG"
    )

    assert without["X-Signature"] != with_query["X-Signature"]


def test_every_attempt_gets_a_fresh_nonce():
    """A replayed nonce is an auth failure at DNSE (10-minute replay window), so a retry
    must never resend the previous signature."""
    signatures: list[str] = []

    def _get(url: str, headers, timeout: float) -> bytes:
        signatures.append(headers["X-Signature"])
        return json.dumps({"error": "boom"}).encode()

    f = feed(
        http_get=_get,
        retry=RetryPolicy(max_attempts=3, base_delay=0.0),
        sleep_fn=lambda _: None,
    )
    with pytest.raises(DnseFeedError):
        f.fetch_closed(datetime(2026, 7, 23, 3, 0, tzinfo=UTC))

    assert len(signatures) == 3
    assert len(set(signatures)) == 3


def test_missing_credentials_fail_closed():
    with pytest.raises(ConfigError, match="DNSE_API_KEY"):
        DnseCredentials.from_env({})


# ------------------------------------------------------------------- bar timestamps
def test_daily_bars_are_anchored_at_the_vn_session_open():
    f = feed(http_get=responder(payload(daily_ts(20, 21))))

    df = f.fetch_closed(datetime(2026, 7, 23, 3, 0, tzinfo=UTC))

    assert [ts.hour for ts in df.index] == [SESSION_OPEN_UTC_HOUR] * 2
    assert list(df.index) == [
        datetime(2026, 7, 20, 2, 0, tzinfo=UTC),
        datetime(2026, 7, 21, 2, 0, tzinfo=UTC),
    ]


@pytest.mark.parametrize(
    "stamped",
    [
        datetime(2026, 7, 19, 17, 0, tzinfo=UTC),  # 00:00 ICT of the 20th
        datetime(2026, 7, 20, 0, 0, tzinfo=UTC),  # 00:00 UTC (07:00 ICT) of the 20th
        datetime(2026, 7, 20, 2, 0, tzinfo=UTC),  # already the session open
        datetime(2026, 7, 20, 7, 45, tzinfo=UTC),  # session close, 14:45 ICT
    ],
)
def test_daily_normalisation_is_idempotent_across_venue_conventions(stamped):
    """We cannot see the venue's real daily convention without a key, so the mapping is
    built to reduce every plausible one to the same ICT trading date."""
    assert normalize_bar_ts(stamped, "1D") == datetime(2026, 7, 20, 2, 0, tzinfo=UTC)


def test_weekly_bars_anchor_to_the_monday_session_open():
    # 2026-07-23 is a Thursday; its ICT week starts Monday 2026-07-20.
    assert normalize_bar_ts(datetime(2026, 7, 23, 5, 0, tzinfo=UTC), "1W") == datetime(
        2026, 7, 20, 2, 0, tzinfo=UTC
    )


def test_intraday_bars_pass_through_untouched():
    ts = datetime(2026, 7, 20, 3, 15, tzinfo=UTC)
    assert normalize_bar_ts(ts, "15m") == ts


def test_vn_session_open_is_0200_utc_year_round():
    """Asia/Ho_Chi_Minh has no DST — assert it, because half the grid logic assumes it."""
    for month in (1, 4, 7, 10):
        assert vn_session_open(datetime(2026, month, 15, 12, 0, tzinfo=UTC)).hour == 2


# -------------------------------------------------------------------- closed bars
def test_forming_bar_is_dropped():
    f = feed(http_get=responder(payload(daily_ts(20, 21, 22))))

    # 2026-07-22 06:00 UTC: the 22nd's bar opened at 02:00 and closes at 02:00 on the
    # 23rd, so only the 20th and 21st are closed.
    df = f.fetch_closed(datetime(2026, 7, 22, 6, 0, tzinfo=UTC))

    assert list(df.index) == [
        datetime(2026, 7, 20, 2, 0, tzinfo=UTC),
        datetime(2026, 7, 21, 2, 0, tzinfo=UTC),
    ]


def test_bar_closes_exactly_at_open_plus_duration():
    f = feed(http_get=responder(payload(daily_ts(20, 21))))

    # 02:00 on the 22nd is exactly `open + 1D` for the 21st bar -> closed side.
    df = f.fetch_closed(datetime(2026, 7, 22, 2, 0, tzinfo=UTC))

    assert datetime(2026, 7, 21, 2, 0, tzinfo=UTC) in df.index


# ------------------------------------------------------------------- price scaling
def test_stock_prices_are_scaled_from_thousand_vnd_to_vnd():
    """DNSE quotes HPG at 24.35 meaning 24,350 VND; every instrument spec, fixture and
    dataset in this repo is in whole VND (pip = 1.0 VND)."""
    f = feed(market_type="STOCK", http_get=responder(payload(daily_ts(20), price=24.0)))

    df = f.fetch_closed(datetime(2026, 7, 23, 3, 0, tzinfo=UTC))

    assert df["open"].iloc[0] == pytest.approx(24.0 * STOCK_PRICE_SCALE)
    assert df["close"].iloc[0] == pytest.approx(24.25 * STOCK_PRICE_SCALE)
    # Volume is a share count, not a price — never scaled.
    assert df["volume"].iloc[0] == pytest.approx(1000.0)


def test_derivative_prices_are_index_points_and_not_scaled():
    f = feed(
        market_type="DERIVATIVE",
        http_get=responder(payload(daily_ts(20), price=1881.0)),
    )

    df = f.fetch_closed(datetime(2026, 7, 23, 3, 0, tzinfo=UTC))

    assert df["open"].iloc[0] == pytest.approx(1881.0)


def test_index_prices_are_not_scaled():
    f = feed(market_type="INDEX", http_get=responder(payload(daily_ts(20), price=1696.87)))

    assert f.fetch_closed(datetime(2026, 7, 23, 3, 0, tzinfo=UTC))["open"].iloc[0] == pytest.approx(
        1696.87
    )


# ---------------------------------------------------------------------- the request
def test_request_carries_symbol_type_resolution_and_epoch_window():
    calls: list[str] = []
    f = feed(market_type="DERIVATIVE", http_get=responder(payload(daily_ts(20)), calls))
    f.symbol = "VN30F1M"

    f.fetch_closed(datetime(2026, 7, 23, 3, 0, tzinfo=UTC), limit=10)

    assert len(calls) == 1
    assert "symbol=VN30F1M" in calls[0]
    assert "type=DERIVATIVE" in calls[0]
    assert "resolution=1D" in calls[0]
    assert "from=" in calls[0] and "to=" in calls[0]


def test_unknown_timeframe_is_rejected_including_4h():
    """DNSE has no 4H resolution. The VN profile forces 1D anyway (plan 05), but a bad
    override must fail loudly rather than silently fetch the wrong frame."""
    with pytest.raises(FeedError, match="no DNSE resolution"):
        feed(timeframe="4H")


def test_invalid_market_type_is_rejected():
    with pytest.raises(FeedError, match="market_type"):
        feed(market_type="FUTURES")


def test_market_type_for_maps_d11_symbol_types():
    assert market_type_for("STOCK_VN_CASH") == "STOCK"
    assert market_type_for("STOCK_VN_DERIV") == "DERIVATIVE"
    with pytest.raises(ConfigError):
        market_type_for("CRYPTO")


def test_error_payload_without_t_array_raises_after_retries():
    f = feed(
        http_get=responder({"message": "Rate Limit Exceeded"}),
        retry=RetryPolicy(max_attempts=2, base_delay=0.0),
        sleep_fn=lambda _: None,
    )

    with pytest.raises(DnseFeedError, match="venue error"):
        f.fetch_closed(datetime(2026, 7, 23, 3, 0, tzinfo=UTC))


def test_ragged_payload_is_rejected():
    bad = payload(daily_ts(20, 21))
    bad["v"] = [1.0]

    f = feed(http_get=responder(bad), retry=RetryPolicy(max_attempts=1))

    with pytest.raises(DnseFeedError, match="ragged"):
        f.fetch_closed(datetime(2026, 7, 23, 3, 0, tzinfo=UTC))


def test_transport_failure_is_retried_then_degrades():
    attempts = {"n": 0}

    def _get(url, headers, timeout):
        attempts["n"] += 1
        raise TimeoutError("slow")

    f = feed(
        http_get=_get,
        retry=RetryPolicy(max_attempts=4, base_delay=0.0),
        sleep_fn=lambda _: None,
    )
    with pytest.raises(DnseFeedError):
        f.fetch_closed(datetime(2026, 7, 23, 3, 0, tzinfo=UTC))

    assert attempts["n"] == 4


# ------------------------------------------------------------------------ backfill
def test_backfill_pages_backwards_until_target_is_met():
    """Each window returns a distinct block of days; the pager must walk back rather
    than re-request the same window forever."""
    now = datetime(2026, 7, 23, 3, 0, tzinfo=UTC)
    windows: list[tuple[int, int]] = []

    def _get(url, headers, timeout):
        from urllib.parse import parse_qs, urlparse

        q = parse_qs(urlparse(url).query)
        start, end = int(q["from"][0]), int(q["to"][0])
        windows.append((start, end))
        times = []
        cursor = datetime(2026, 7, 22, 2, 0, tzinfo=UTC)
        while cursor.timestamp() >= start:
            if start <= cursor.timestamp() <= end:
                times.append(int(cursor.timestamp()))
            cursor -= timedelta(days=1)
            if len(times) > 500:
                break
        return json.dumps(payload(sorted(times))).encode()

    f = feed(http_get=_get)
    df = f.backfill(now, bars=700)

    assert len(df) == 700
    assert df.index.is_monotonic_increasing
    assert not df.index.duplicated().any()
    assert len(windows) >= 2
    assert windows[1][1] < windows[0][1]  # walked backwards


def test_backfill_stops_on_two_consecutive_empty_windows():
    calls: list[str] = []
    f = feed(http_get=responder(payload([]), calls))

    df = f.backfill(datetime(2026, 7, 23, 3, 0, tzinfo=UTC), bars=2100)

    assert df.empty
    assert len(calls) == 2  # one empty window may be a holiday; two ends the walk


def test_short_history_is_not_an_error():
    """VN30F1M has only traded since 2017, so asking for 2100 daily bars legitimately
    returns fewer. The engine answers wait/warmup (C12) — the feed must not raise."""
    f = feed(http_get=responder(payload(daily_ts(20, 21))))

    df = f.backfill(datetime(2026, 7, 23, 3, 0, tzinfo=UTC), bars=2100)

    assert len(df) == 2


# ------------------------------------------------------------------ poll scheduling
def test_next_close_for_daily_is_the_next_session_open():
    f = feed()

    # Mid-session on 2026-07-22 -> that bar closes when the 23rd opens.
    assert f.next_close_after(datetime(2026, 7, 22, 6, 0, tzinfo=UTC)) == datetime(
        2026, 7, 23, 2, 0, tzinfo=UTC
    )
    # Exactly at a session open -> strictly after, so the next day.
    assert f.next_close_after(datetime(2026, 7, 22, 2, 0, tzinfo=UTC)) == datetime(
        2026, 7, 23, 2, 0, tzinfo=UTC
    )


def test_next_close_for_weekly_is_the_next_monday_session_open():
    f = feed(timeframe="1W")

    assert f.next_close_after(datetime(2026, 7, 22, 6, 0, tzinfo=UTC)) == datetime(
        2026, 7, 27, 2, 0, tzinfo=UTC
    )


def test_next_close_for_intraday_is_epoch_aligned():
    f = feed(timeframe="15m")

    assert f.next_close_after(datetime(2026, 7, 22, 3, 7, tzinfo=UTC)) == datetime(
        2026, 7, 22, 3, 15, tzinfo=UTC
    )
    # 09:00 ICT is 02:00 UTC, which is on the 15m epoch grid — no VN special case needed.
    assert f.next_close_after(datetime(2026, 7, 22, 1, 50, tzinfo=UTC)) == datetime(
        2026, 7, 22, 2, 0, tzinfo=UTC
    )


def test_secret_does_not_leak_into_the_feed_repr():
    """A `LiveFeedError` traceback or a debug log line prints the feed; the secret must
    not ride along."""
    assert "test_secret" not in repr(feed())


def test_encoded_signature_decodes_back_to_the_raw_digest():
    raw = b"\x01\x02\x03\xfb\xff"
    unescaped = encode_signature(raw).replace("%2B", "+").replace("%2F", "/").replace("%3D", "=")
    assert base64.b64decode(unescaped) == raw

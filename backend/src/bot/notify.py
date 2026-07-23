"""Alerts for the live runner (plan 07 §4). Telegram if configured, log otherwise.

Two properties matter more than the feature list:

* **No token, no problem.** `build_notifier()` falls back to a log-only sink, so a live
  run started without `TELEGRAM_BOT_TOKEN` behaves identically minus the messages.
* **An alert can never take the bot down.** Delivery failures are logged and swallowed:
  the point of the alert channel is to report trouble, so it must not become trouble.

Plan 13 turns this into a shared event bus (Telegram + web toast + DB table); the
formatting entry points here are deliberately event-shaped so that later refactor is a
re-wiring rather than a rewrite.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from typing import Protocol

logger = logging.getLogger("bot.notify")

TELEGRAM_API = "https://api.telegram.org"

#: (url, data, timeout) -> response body. Injected so tests never touch a socket.
HttpPostFn = Callable[[str, bytes, float], bytes]


def urllib_post(url: str, data: bytes, timeout: float) -> bytes:
    request = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        body: bytes = response.read()
    return body


class Notifier(Protocol):
    def send(self, text: str) -> None: ...


class LogNotifier:
    """The fallback sink: everything still shows up, just in the log."""

    def __init__(self) -> None:
        self.sent: list[str] = []

    def send(self, text: str) -> None:
        self.sent.append(text)
        logger.info("ALERT %s", text)


class TelegramNotifier:
    def __init__(
        self,
        token: str,
        chat_id: str,
        http_post: HttpPostFn | None = None,
        timeout: float = 10.0,
    ) -> None:
        self.token = token
        self.chat_id = chat_id
        self.http_post = http_post if http_post is not None else urllib_post
        self.timeout = timeout

    def send(self, text: str) -> None:
        url = f"{TELEGRAM_API}/bot{self.token}/sendMessage"
        payload = urllib.parse.urlencode({"chat_id": self.chat_id, "text": text}).encode()
        try:
            self.http_post(url, payload, self.timeout)
        except (urllib.error.URLError, OSError, ValueError, TimeoutError) as exc:
            # Swallowed on purpose: a dead alert channel must not kill the trading loop.
            logger.warning("telegram delivery failed: %s (message: %s)", exc, text)


def build_notifier(
    env: Mapping[str, str] | None = None, http_post: HttpPostFn | None = None
) -> Notifier:
    environ = env if env is not None else os.environ
    token = environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = environ.get("TELEGRAM_CHAT_ID", "").strip()
    if token and chat_id:
        return TelegramNotifier(token, chat_id, http_post=http_post)
    if token or chat_id:
        logger.warning(
            "telegram half-configured (need BOTH TELEGRAM_BOT_TOKEN and "
            "TELEGRAM_CHAT_ID) -- falling back to log-only alerts"
        )
    return LogNotifier()


class LiveAlerts:
    """Formats the plan 07 event set and remembers what it has already said.

    The dedupe state is what keeps a 48h run from spamming: `feed_degraded` fires on the
    transition into degraded (not once per failed poll), and the daily summary fires
    once per trading day."""

    def __init__(self, notifier: Notifier, run_label: str = "live") -> None:
        self.notifier = notifier
        self.run_label = run_label
        self._degraded = False
        self._summary_day: str | None = None

    def _send(self, text: str) -> None:
        self.notifier.send(f"[{self.run_label}] {text}")

    def trade_opened(self, symbol: str, direction: str, strategy: str, equity: float) -> None:
        self._send(f"OPEN {symbol} {direction} ({strategy}) — equity {equity:,.2f}")

    def trade_closed(
        self, symbol: str, result: str, pnl_r: float, pnl_amount: float, equity: float
    ) -> None:
        self._send(
            f"CLOSE {symbol} {result} {pnl_r:+.2f}R ({pnl_amount:+,.2f}) " f"— equity {equity:,.2f}"
        )

    def feed_degraded(self, detail: str) -> None:
        if self._degraded:
            return
        self._degraded = True
        self._send(f"⚠️ feed DEGRADED — {detail}")

    def feed_recovered(self) -> None:
        if not self._degraded:
            return
        self._degraded = False
        self._send("✅ feed recovered")

    def crashed(self, detail: str) -> None:
        self._send(f"🛑 runner crashed — {detail}")

    def stopped(self, detail: str) -> None:
        self._send(f"⏹ runner stopped — {detail}")

    def daily_summary(self, day: str, stats: Mapping[str, object]) -> None:
        if self._summary_day == day:
            return
        self._summary_day = day
        self._send(f"📊 daily summary {day} — {json.dumps(dict(stats), default=str)}")

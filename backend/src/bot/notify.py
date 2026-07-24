"""Alert formatting + the Telegram transport (plans 07 and 13).

Two properties matter more than the feature list:

* **No token, no problem.** `build_notifier()` falls back to a log-only sink, so a live
  run started without `TELEGRAM_BOT_TOKEN` behaves identically minus the messages.
* **An alert can never take the bot down.** Delivery failures are logged and reported as
  a `False` return, never raised: the point of the alert channel is to report trouble,
  so it must not become trouble.

Plan 13 splits this module in two along the seam that was already here:

* `LiveAlerts` is the **formatter** — it turns "a trade closed" into a code, a level, a
  human title and a structured body, and it remembers what it has already said.
* an `AlertEmitter` is the **transport** — where those events go. The fallback
  (`NotifierEmitter`) pushes text at a `Notifier`, exactly as plan 07 did. The real one
  is `bot.alerts.bus.AlertBus`, which additionally writes the DB row the web UI polls.

The split is what keeps `bot/engine/*` free of any `bot.alerts` import (invariant #6,
`test_dependency_direction`): the live runner talks to `LiveAlerts`, and whoever builds
the session decides which transport is behind it.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
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
    #: True when this sink actually reaches the user's phone. The alert log records
    #: `sent_telegram` from it, so a token-less deployment does not claim to have
    #: messaged anyone just because the fallback logger accepted the line.
    remote: bool

    def send(self, text: str) -> bool:
        """Deliver `text`. Returns True on success, False on a (logged) failure —
        never raises, so a dead channel cannot kill the trading loop."""
        ...


class LogNotifier:
    """The fallback sink: everything still shows up, just in the log."""

    remote = False

    def __init__(self) -> None:
        self.sent: list[str] = []

    def send(self, text: str) -> bool:
        self.sent.append(text)
        logger.info("ALERT %s", text)
        return True


class TelegramNotifier:
    remote = True

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

    def send(self, text: str) -> bool:
        url = f"{TELEGRAM_API}/bot{self.token}/sendMessage"
        payload = urllib.parse.urlencode({"chat_id": self.chat_id, "text": text}).encode()
        try:
            self.http_post(url, payload, self.timeout)
        except (urllib.error.URLError, OSError, ValueError, TimeoutError) as exc:
            # Swallowed on purpose: a dead alert channel must not kill the trading loop.
            # The caller learns about it from the False return (the bus records
            # `telegram_status='failed'` and retries on a later emit).
            logger.warning("telegram delivery failed: %s (message: %s)", exc, text)
            return False
        return True


def build_notifier(
    env: Mapping[str, str] | None = None, http_post: HttpPostFn | None = None
) -> Notifier:
    from bot import settings

    token, chat_id = settings.telegram_credentials(env)
    if token and chat_id:
        return TelegramNotifier(token, chat_id, http_post=http_post)
    if token or chat_id:
        logger.warning(
            "telegram half-configured (need BOTH TELEGRAM_BOT_TOKEN and "
            "TELEGRAM_CHAT_ID) -- falling back to log-only alerts"
        )
    return LogNotifier()


# ---------------------------------------------------------------------------
# Plan 13: the event shape and the transport seam.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AlertEvent:
    """One thing worth telling a human about.

    `level` is deliberately optional: the severity of a code is a property of the
    catalogue (`bot.alerts.codes`), not of the call site, and this module must not
    import that catalogue — doing so would drag `bot.alerts` into everything that
    imports `bot.notify`, including `bot/engine`. `None` means "use the catalogue".
    """

    code: str
    title: str
    body: Mapping[str, object] = field(default_factory=dict)
    level: str | None = None
    #: Groups alerts for the cooldown window (usually the symbol). Same code + same key
    #: inside the window = one Telegram message. Empty = the code alone is the key.
    dedupe_key: str = ""


class AlertEmitter(Protocol):
    def emit(self, event: AlertEvent) -> None: ...


class NotifierEmitter:
    """Plan 07's behaviour, expressed as an emitter: format the event as one line of
    text and push it at a `Notifier`. No DB, no cooldown, no web toast — this is what
    you get when nobody wired an `AlertBus`."""

    def __init__(self, notifier: Notifier | None = None, run_label: str = "live") -> None:
        self.notifier = notifier if notifier is not None else LogNotifier()
        self.run_label = run_label

    def emit(self, event: AlertEvent) -> None:
        self.notifier.send(f"[{self.run_label}] {event.title}")


class LiveAlerts:
    """Formats the plan 07/13 event set and remembers what it has already said.

    The dedupe state here is *transition* dedupe, not the bus's cooldown: `feed_degraded`
    fires on the transition into degraded (not once per failed poll) and the daily summary
    fires once per trading day, regardless of which transport is behind it.
    """

    def __init__(
        self,
        notifier: Notifier | None = None,
        run_label: str = "live",
        emitter: AlertEmitter | None = None,
    ) -> None:
        # When an emitter is given it owns delivery entirely (the AlertBus does its own
        # Telegram send); `notifier` is then unused rather than a second, duplicate
        # channel. Passing neither gives the plan 07 log-only fallback.
        self.emitter: AlertEmitter = (
            emitter if emitter is not None else NotifierEmitter(notifier, run_label)
        )
        self.notifier = notifier
        self.run_label = run_label
        self._degraded = False
        self._summary_day: str | None = None
        self._risk_multiplier = 1.0
        self._drawdown_band = 0  # 0 = healthy, 1 = warn breached, 2 = critical breached

    def _emit(
        self,
        code: str,
        title: str,
        body: Mapping[str, object] | None = None,
        dedupe_key: str = "",
        level: str | None = None,
    ) -> None:
        self.emitter.emit(
            AlertEvent(
                code=code, title=title, body=dict(body or {}), level=level, dedupe_key=dedupe_key
            )
        )

    # ------------------------------------------------------------ trade lifecycle
    def trade_pending(self, symbol: str, direction: str, strategy: str, sl: float | None) -> None:
        self._emit(
            "trade_pending",
            f"PENDING {symbol} {direction} ({strategy}) — chờ retest",
            {"symbol": symbol, "direction": direction, "strategy": strategy, "sl": sl},
            dedupe_key=symbol,
        )

    def trade_opened(
        self,
        symbol: str,
        direction: str,
        strategy: str,
        equity: float,
        entry: float | None = None,
        sl: float | None = None,
        tp1: float | None = None,
        lot: float | None = None,
        risk_pct: float | None = None,
    ) -> None:
        self._emit(
            "trade_opened",
            f"OPEN {symbol} {direction} ({strategy}) — equity {equity:,.2f}",
            {
                "symbol": symbol,
                "direction": direction,
                "strategy": strategy,
                "entry": entry,
                "sl": sl,
                "tp1": tp1,
                "lot": lot,
                "risk_pct": risk_pct,
                "equity": equity,
            },
            dedupe_key=symbol,
        )

    def trade_cancelled(self, symbol: str, detail: str) -> None:
        self._emit(
            "trade_cancelled",
            f"CANCEL {symbol} — {detail}",
            {"symbol": symbol, "detail": detail},
            dedupe_key=symbol,
        )

    def tp1_hit(self, symbol: str, equity: float) -> None:
        self._emit(
            "tp1_hit",
            f"TP1 {symbol} — chốt một phần, SL về BE (equity {equity:,.2f})",
            {"symbol": symbol, "equity": equity},
            dedupe_key=symbol,
        )

    def trade_closed(
        self, symbol: str, result: str, pnl_r: float, pnl_amount: float, equity: float
    ) -> None:
        self._emit(
            "trade_closed",
            f"CLOSE {symbol} {result} {pnl_r:+.2f}R ({pnl_amount:+,.2f}) — equity {equity:,.2f}",
            {
                "symbol": symbol,
                "result": result,
                "pnl_r": pnl_r,
                "pnl_amount": pnl_amount,
                "equity": equity,
            },
            dedupe_key=symbol,
        )

    # ------------------------------------------------------------- account risk
    def daily_loss_limit(self, day: str, losses: int) -> None:
        self._emit(
            "daily_loss_limit",
            f"⛔ chạm giới hạn {losses} lệnh thua ngày {day} — nghỉ hết ngày",
            {"trading_day": day, "losses": losses},
            dedupe_key=day,
        )

    def equity_multiplier(self, multiplier: float, wins: int, losses: int) -> None:
        """Fires on a CHANGE of the equity-curve multiplier, not on every bar that
        reports the same value."""
        if multiplier == self._risk_multiplier:
            return
        previous, self._risk_multiplier = self._risk_multiplier, multiplier
        self._emit(
            "equity_multiplier",
            f"⚖️ risk multiplier {previous:g}× → {multiplier:g}× "
            f"(chuỗi thắng {wins}, chuỗi thua {losses})",
            {
                "multiplier": multiplier,
                "previous": previous,
                "consecutive_wins": wins,
                "consecutive_losses": losses,
            },
        )

    def drawdown(self, drawdown_pct: float, equity: float, peak: float, level: str) -> None:
        """`level` is 'warn' or 'critical' — the caller owns the thresholds (plan 08 §2:
        5% / 10%) and the band bookkeeping that stops this from firing per bar."""
        code = "drawdown_critical" if level == "critical" else "drawdown_warn"
        icon = "🛑" if level == "critical" else "⚠️"
        self._emit(
            code,
            f"{icon} drawdown {drawdown_pct:.2f}% từ đỉnh {peak:,.2f} "
            f"(equity {equity:,.2f})",
            {"drawdown_pct": drawdown_pct, "equity": equity, "peak_equity": peak},
        )

    # ------------------------------------------------------------- process health
    def started(self, detail: str, symbols: list[str] | None = None) -> None:
        self._emit(
            "runner_started",
            f"▶️ runner started — {detail}",
            {"detail": detail, "symbols": symbols or []},
        )

    def feed_degraded(self, detail: str) -> None:
        if self._degraded:
            return
        self._degraded = True
        self._emit("feed_degraded", f"⚠️ feed DEGRADED — {detail}", {"detail": detail})

    def feed_recovered(self) -> None:
        if not self._degraded:
            return
        self._degraded = False
        self._emit("feed_recovered", "✅ feed recovered")

    def crashed(self, detail: str) -> None:
        self._emit("runner_crashed", f"🛑 runner crashed — {detail}", {"detail": detail})

    def stopped(self, detail: str) -> None:
        self._emit("runner_stopped", f"⏹ runner stopped — {detail}", {"detail": detail})

    def daily_summary(self, day: str, stats: Mapping[str, object]) -> None:
        if self._summary_day == day:
            return
        self._summary_day = day
        self._emit(
            "daily_summary",
            f"📊 daily summary {day} — {json.dumps(dict(stats), default=str)}",
            {"trading_day": day, **dict(stats)},
            dedupe_key=day,
        )

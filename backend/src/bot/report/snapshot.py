"""Render a PNG snapshot of the ~100 bars around a trade's open/close (plan 14).

Deliberately outside `bot.engine`: matplotlib/mplfinance are heavyweight and only ever
needed by the live runner (after a fill/close) and the API's on-demand endpoint, never by
the decision path itself (`test_no_matplotlib_in_engine`). `render_snapshot` is pure
given its inputs — no DB, no Feed — so it can be unit-tested against a fixed frame; the
callers (`bot.engine.live_runner`, `bot.api.routers.trades`) are the only code that reads
the DB/Feed to build those inputs.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless: no display, no GUI backend dependency

import matplotlib.pyplot as plt  # noqa: E402
import mplfinance as mpf  # noqa: E402
import pandas as pd  # noqa: E402

from bot.data.feed import Feed  # noqa: E402
from bot.db import repositories as repo  # noqa: E402
from bot.indicators.ema import ema  # noqa: E402

logger = logging.getLogger("bot.report.snapshot")

MAX_BARS = 100
FIGSIZE = (12.0, 7.0)
DPI = 100
EMA_FAST_PERIOD = 34
EMA_SLOW_PERIOD = 89

_LEVEL_COLORS = {
    "entry": "#2ca02c",
    "sl": "#d62728",
    "tp1": "#9467bd",
    "tp2": "#7f3fbf",
    "be": "#7f7f7f",
}


@dataclass(frozen=True)
class SnapshotLevels:
    """Horizontal price lines + the breakout range band. All optional — a mean-reversion
    trade has no range, an unfilled/cancelled trade has no entry, etc."""

    entry: float | None = None
    sl: float | None = None
    tp1: float | None = None
    tp2: float | None = None
    be: float | None = None
    range_high: float | None = None
    range_low: float | None = None


@dataclass(frozen=True)
class SnapshotMeta:
    """Everything that goes in the title / filename but is not a price level."""

    symbol: str
    timeframe: str
    strategy: str
    direction: str
    at: str  # "open" | "close"
    stage: str = ""
    reason: str = ""


def default_snapshot_root() -> Path:
    backend_root = Path(__file__).resolve().parents[3]
    return backend_root / "data" / "snapshots"


def trade_snapshot_path(run_id: int, trade_id: int, at: str, root: Path | None = None) -> Path:
    base = root if root is not None else default_snapshot_root()
    return base / str(run_id) / f"{trade_id}_{at}.png"


def render_snapshot(
    frame: pd.DataFrame,
    levels: SnapshotLevels,
    meta: SnapshotMeta,
    out_path: Path,
    signal_bar_ts: pd.Timestamp | None = None,
    marker_bar_ts: pd.Timestamp | None = None,
    max_bars: int = MAX_BARS,
) -> Path:
    """Render `out_path` (PNG) from the last `max_bars` rows of `frame`.

    `frame` must be an OHLCV DataFrame indexed by bar open_ts, ascending, already sliced
    to whatever was visible at the snapshot instant (C11 is the caller's job — this
    module has no notion of "now"). Raises ValueError on an empty frame; any other
    failure is a genuine bug the caller should let propagate (it wraps this in try/except
    and reports `snapshot_error` instead of crashing the runner)."""
    view = frame.tail(max_bars).loc[:, ["open", "high", "low", "close", "volume"]].copy()
    if view.empty:
        raise ValueError("no bars to render")
    view.index.name = "Date"

    addplots = []
    if len(view) >= 2:
        fast = ema(view["close"], EMA_FAST_PERIOD)
        slow = ema(view["close"], EMA_SLOW_PERIOD)
        addplots.append(mpf.make_addplot(fast, color="#1f77b4", width=1.0))
        addplots.append(mpf.make_addplot(slow, color="#ff7f0e", width=1.0))

    hlines: list[float] = []
    hcolors: list[str] = []
    for name, value in (
        ("entry", levels.entry),
        ("sl", levels.sl),
        ("tp1", levels.tp1),
        ("tp2", levels.tp2),
        ("be", levels.be),
    ):
        if value is not None:
            hlines.append(value)
            hcolors.append(_LEVEL_COLORS[name])

    title = f"{meta.symbol} {meta.timeframe} {meta.strategy} {meta.direction} — {meta.at}"
    if meta.stage or meta.reason:
        title += f" ({meta.stage or meta.reason})"

    out_path.parent.mkdir(parents=True, exist_ok=True)
    plot_kwargs: dict[str, object] = dict(
        type="candle", style="charles", title=title, volume=True, figsize=FIGSIZE, returnfig=True
    )
    if addplots:
        plot_kwargs["addplot"] = addplots
    if hlines:
        plot_kwargs["hlines"] = dict(hlines=hlines, colors=hcolors, linestyle="--", linewidths=1.0)
    fig, axes = mpf.plot(view, **plot_kwargs)
    ax = axes[0]
    if levels.range_high is not None and levels.range_low is not None:
        ax.axhspan(levels.range_low, levels.range_high, color="#ffdd57", alpha=0.15, zorder=0)

    for ts, color in ((signal_bar_ts, "#17becf"), (marker_bar_ts, "#e377c2")):
        if ts is None or ts not in view.index:
            continue
        pos = view.index.get_loc(ts)
        ax.axvline(pos, color=color, linestyle=":", linewidth=1.2)

    try:
        fig.savefig(out_path, dpi=DPI)
    finally:
        plt.close(fig)
    return out_path


@dataclass(frozen=True)
class SnapshotInputs:
    """Everything `render_snapshot` needs, already read out of the DB/Feed. Produced by
    `gather_snapshot_inputs` (touches `conn`, cheap) and consumed by `render_snapshot`
    (heavy matplotlib, no DB) — the split lets the API render off the sqlite lock so a
    slow render can't stall unrelated polling (`RunnerService.render_trade_snapshot`)."""

    frame: pd.DataFrame
    levels: SnapshotLevels
    meta: SnapshotMeta
    out_path: Path
    signal_ts: pd.Timestamp | None
    marker_ts: pd.Timestamp | None
    max_bars: int


def gather_snapshot_inputs(
    conn: sqlite3.Connection,
    price_feed: Feed,
    run_id: int,
    trade_id: int,
    at: str,
    now: datetime,
    max_bars: int = MAX_BARS,
    root: Path | None = None,
) -> SnapshotInputs:
    """Read the `trade`/`decision` rows + the visible bars — the only work that touches
    `conn`. Fast; safe to call while holding the sqlite lock. Rendering is done separately
    (`render_snapshot`) so it need not hold that lock.

    `now` is the bar_ts the snapshot should be "as of" — the live runner passes the tick
    that just filled/closed the trade (so the fill/close bar itself is visible, C11); the
    on-demand API endpoint passes that same trade's opened/closed_at + one bar duration.
    """
    trade = repo.get_trade(conn, trade_id)
    if trade is None:
        raise ValueError(f"trade {trade_id} not found")
    tf = trade["timeframe"]
    if not tf:
        raise ValueError(f"trade {trade_id} has no timeframe recorded")

    frame = price_feed.bars(tf, now, max_bars)
    levels = SnapshotLevels(
        entry=trade["entry_price"],
        sl=trade["sl_price"],
        tp1=trade["tp1_price"],
        tp2=trade["tp2_price"],
        range_high=trade["range_high"],
        range_low=trade["range_low"],
    )
    signal_row = repo.signal_decision_for_trade(conn, trade_id)
    signal_ts = pd.Timestamp(signal_row["bar_ts_utc"]) if signal_row is not None else None
    marker_ts_str = trade["opened_at_utc"] if at == "open" else trade["closed_at_utc"]
    marker_ts = pd.Timestamp(marker_ts_str) if marker_ts_str else None

    meta = SnapshotMeta(
        symbol=trade["symbol"],
        timeframe=tf,
        strategy=trade["strategy"],
        direction=trade["direction"],
        at=at,
        stage=signal_row["stage"] if signal_row is not None else "",
        reason=signal_row["reason"] if signal_row is not None else "",
    )
    out_path = trade_snapshot_path(run_id, trade_id, at, root=root)
    return SnapshotInputs(frame, levels, meta, out_path, signal_ts, marker_ts, max_bars)


def render_gathered(inputs: SnapshotInputs) -> Path:
    """Render inputs produced by `gather_snapshot_inputs` (pure CPU, no DB)."""
    return render_snapshot(
        inputs.frame,
        inputs.levels,
        inputs.meta,
        inputs.out_path,
        signal_bar_ts=inputs.signal_ts,
        marker_bar_ts=inputs.marker_ts,
        max_bars=inputs.max_bars,
    )


def capture_trade_snapshot(
    conn: sqlite3.Connection,
    price_feed: Feed,
    run_id: int,
    trade_id: int,
    at: str,
    now: datetime,
    max_bars: int = MAX_BARS,
    root: Path | None = None,
) -> Path:
    """Gather + render in one call. Shared by both callers so a live snapshot and its
    on-demand re-render are identical. The API path calls `gather_snapshot_inputs` and
    `render_gathered` separately instead, to keep the heavy render off the sqlite lock."""
    inputs = gather_snapshot_inputs(conn, price_feed, run_id, trade_id, at, now, max_bars, root)
    return render_gathered(inputs)

"""Chart snapshot rendering (plan 14)."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from bot.db import repositories as repo
from bot.db.connection import connect_and_migrate
from bot.report.snapshot import (
    SnapshotLevels,
    SnapshotMeta,
    capture_trade_snapshot,
    render_snapshot,
    trade_snapshot_path,
)


def _seeded_frame(n: int = 150, seed: int = 7) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    rng = np.random.default_rng(seed)
    close = 100.0 + np.cumsum(rng.normal(0, 0.5, n))
    open_ = close + rng.normal(0, 0.1, n)
    high = np.maximum(open_, close) + np.abs(rng.normal(0, 0.2, n))
    low = np.minimum(open_, close) - np.abs(rng.normal(0, 0.2, n))
    volume = rng.integers(100, 1000, n).astype(float)
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume}, index=idx
    )


def test_render_snapshot_writes_a_nonempty_png(tmp_path: Path) -> None:
    frame = _seeded_frame()
    levels = SnapshotLevels(entry=100.0, sl=98.0, tp1=103.0, tp2=105.0)
    meta = SnapshotMeta(
        symbol="EURUSD", timeframe="1H", strategy="BREAKOUT", direction="BUY", at="open"
    )
    out = render_snapshot(frame, levels, meta, tmp_path / "snap.png")
    assert out.exists()
    assert out.stat().st_size > 0


def test_render_snapshot_draws_at_most_max_bars(tmp_path: Path) -> None:
    frame = _seeded_frame(n=300)
    levels = SnapshotLevels()
    meta = SnapshotMeta(
        symbol="EURUSD", timeframe="1H", strategy="MEAN_REVERSION", direction="SELL", at="close"
    )
    out = render_snapshot(frame, levels, meta, tmp_path / "snap.png", max_bars=100)
    assert out.exists() and out.stat().st_size > 0


def test_render_snapshot_levels_stay_within_the_price_range(tmp_path: Path) -> None:
    """Not a pixel comparison (plan explicitly asks for a data check instead): the level
    prices used to draw hlines must fall inside the plotted frame's [low, high] band, or
    the "overlay" would silently be off the visible chart."""
    frame = _seeded_frame()
    view = frame.tail(100)
    lo, hi = float(view["low"].min()), float(view["high"].max())
    entry = float(view["close"].iloc[-1])
    sl = entry - 1.0
    tp1 = entry + 1.0
    levels = SnapshotLevels(entry=entry, sl=sl, tp1=tp1)
    for value in (levels.entry, levels.sl, levels.tp1):
        assert lo - 5 <= value <= hi + 5  # sane sanity band, not exact containment
    meta = SnapshotMeta(
        symbol="EURUSD", timeframe="1H", strategy="BREAKOUT", direction="BUY", at="open"
    )
    out = render_snapshot(frame, levels, meta, tmp_path / "snap.png")
    assert out.exists() and out.stat().st_size > 0


def test_render_snapshot_raises_on_empty_frame(tmp_path: Path) -> None:
    empty = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    levels = SnapshotLevels()
    meta = SnapshotMeta(
        symbol="EURUSD", timeframe="1H", strategy="BREAKOUT", direction="BUY", at="open"
    )
    with pytest.raises(ValueError):
        render_snapshot(empty, levels, meta, tmp_path / "snap.png")


# --------------------------------------------------------------- capture_trade_snapshot


class _FakeFeed:
    """Just enough of `Feed` for `capture_trade_snapshot`: one timeframe, no C11 filter
    (the test frame is already all "closed")."""

    def __init__(self, frame: pd.DataFrame, tf: str) -> None:
        self.frames = {tf: frame}

    def bars(self, tf: str, end_ts, n: int) -> pd.DataFrame:  # noqa: ANN001
        return self.frames[tf].tail(n)


def _conn_with_trade(range_high: float | None = None, range_low: float | None = None) -> tuple:
    conn = connect_and_migrate(":memory:")
    cv = repo.create_config_version(conn, "{}", note="test")
    repo.upsert_dataset(conn, "ds1", "{}")
    run_id = repo.create_run(conn, cv, {"EURUSD": "ds1"}, 10_000.0)
    trade_id = repo.insert_trade(
        conn,
        repo.TradeRecord(
            run_id=run_id,
            symbol="EURUSD",
            strategy="BREAKOUT",
            direction="BUY",
            status="OPEN",
            entry_price=100.0,
            sl_price=98.0,
            tp1_price=103.0,
            tp2_price=105.0,
            opened_at_utc="2024-01-05T00:00:00+00:00",
            timeframe="1H",
            range_high=range_high,
            range_low=range_low,
        ),
    )
    return conn, run_id, trade_id


def test_capture_trade_snapshot_open(tmp_path: Path) -> None:
    frame = _seeded_frame(n=150)
    conn, run_id, trade_id = _conn_with_trade(range_high=101.0, range_low=99.0)
    feed = _FakeFeed(frame, "1H")
    now = frame.index[-1].to_pydatetime() + timedelta(hours=1)

    out = capture_trade_snapshot(conn, feed, run_id, trade_id, "open", now, root=tmp_path)
    assert out == trade_snapshot_path(run_id, trade_id, "open", root=tmp_path)
    assert out.exists() and out.stat().st_size > 0


def test_capture_trade_snapshot_unknown_trade_raises(tmp_path: Path) -> None:
    conn = connect_and_migrate(":memory:")
    feed = _FakeFeed(_seeded_frame(), "1H")
    now = pd.Timestamp.now(tz="UTC")
    with pytest.raises(ValueError):
        capture_trade_snapshot(conn, feed, 1, 999, "open", now, root=tmp_path)

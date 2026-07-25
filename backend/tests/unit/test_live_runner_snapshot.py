"""Plan 14: the live runner captures a PNG on fill and on close, and a renderer failure
reports `snapshot_error` instead of crashing the run."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from bot.core.timeframes import tf_duration
from bot.report import snapshot as chart_snapshot
from bot.report.snapshot import trade_snapshot_path
from tests.unit.test_live_runner import (
    TF,
    WARMUP,
    FakeClock,
    FakeSource,
    base_bars,
    crypto_config,
    make_conn,
    make_live,
    make_run,
)


def _drive(live, df, clock) -> None:
    end = df.index[-1].to_pydatetime() + tf_duration(TF) * 2
    while clock() <= end:
        live.poll()
        live.drain()
        clock.advance(tf_duration(TF))


def test_live_run_captures_open_and_close_snapshots(tmp_path: Path) -> None:
    df = base_bars()
    cfg = crypto_config()
    clock = FakeClock(df.index[WARMUP].to_pydatetime() + tf_duration(TF))
    conn = make_conn()
    run_id = make_run(conn, cfg, "live")
    live = make_live(conn, run_id, cfg, FakeSource(df), clock)
    live.snapshot_root = tmp_path
    live.start()
    _drive(live, df, clock)

    closed_trade_ids = [
        int(r[0])
        for r in conn.execute(
            "SELECT id FROM trade WHERE run_id=? AND status='CLOSED'", (run_id,)
        )
    ]
    assert closed_trade_ids, "expected at least one closed trade over the sample"
    for trade_id in closed_trade_ids:
        open_path = trade_snapshot_path(run_id, trade_id, "open", root=tmp_path)
        close_path = trade_snapshot_path(run_id, trade_id, "close", root=tmp_path)
        assert open_path.exists() and open_path.stat().st_size > 0
        assert close_path.exists() and close_path.stat().st_size > 0
    conn.close()


def test_a_renderer_failure_alerts_and_does_not_crash_the_run(tmp_path: Path) -> None:
    from bot.notify import LiveAlerts, LogNotifier

    df = base_bars()
    cfg = crypto_config()
    clock = FakeClock(df.index[WARMUP].to_pydatetime() + tf_duration(TF))
    conn = make_conn()
    run_id = make_run(conn, cfg, "live")
    notifier = LogNotifier()
    live = make_live(conn, run_id, cfg, FakeSource(df), clock, alerts=LiveAlerts(notifier))
    live.snapshot_root = tmp_path
    live.start()

    with patch.object(
        chart_snapshot, "capture_trade_snapshot", side_effect=RuntimeError("boom")
    ):
        _drive(live, df, clock)

    closed = conn.execute(
        "SELECT COUNT(*) FROM trade WHERE run_id=? AND status='CLOSED'", (run_id,)
    ).fetchone()[0]
    assert closed > 0, "the run must still process trades despite the renderer failing"
    assert any("lỗi render ảnh chart" in line for line in notifier.sent)
    conn.close()

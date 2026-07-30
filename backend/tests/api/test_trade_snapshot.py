"""On-demand chart snapshot rendering (plan 14): GET /api/trades/{id}/snapshot."""

from __future__ import annotations

from fastapi.testclient import TestClient


def _run_until_trades(client: TestClient, seed: int, bars: int) -> list[dict]:
    # BRB's Peak1 -> retest -> breakout-2 -> scoring gate (docs/spec_v2.md) cuts entry
    # frequency by design; fall back to v1.2 single-phase entries so this fixed
    # seed/bar-count window reliably produces a CLOSED trade -- these tests are about
    # snapshot rendering, not the strategy (BRB itself is covered by test_strategies.py /
    # test_main_loop.py).
    assert (
        client.patch(
            "/api/config", json={"strategies": {"breakout": {"require_second_breakout": False}}}
        ).status_code
        == 200
    )
    resp = client.post("/api/run", json={"seed": seed, "bars": bars})
    assert resp.status_code == 200
    for _ in range(bars + 10):
        step_resp = client.post("/api/run/step")
        assert step_resp.status_code == 200
        summaries = step_resp.json()
        if summaries and summaries[0]["exhausted"]:
            break
    return client.get("/api/trades", params={"status": "CLOSED"}).json()


def test_on_demand_snapshot_renders_a_png_for_a_backtest_trade(client: TestClient) -> None:
    trades = _run_until_trades(client, seed=42, bars=3000)
    assert trades, "expected at least one CLOSED trade over 3000 bars"
    trade_id = trades[0]["id"]

    for at in ("open", "close"):
        resp = client.get(f"/api/trades/{trade_id}/snapshot", params={"at": at})
        assert resp.status_code == 200, resp.text
        assert resp.headers["content-type"] == "image/png"
        assert len(resp.content) > 0


def test_on_demand_snapshot_is_repeatable(client: TestClient) -> None:
    trades = _run_until_trades(client, seed=42, bars=3000)
    trade_id = trades[0]["id"]

    first = client.get(f"/api/trades/{trade_id}/snapshot", params={"at": "open"})
    second = client.get(f"/api/trades/{trade_id}/snapshot", params={"at": "open"})
    assert first.status_code == second.status_code == 200
    assert len(second.content) > 0


def test_on_demand_snapshot_ignores_a_stale_file_on_disk(client: TestClient) -> None:
    """Regression: `snapshots/{run_id}/{trade_id}_{at}.png` is keyed by ids that are only
    unique within one DB lifetime. A leftover file (recreated DB, or a different symbol's
    old run reusing the same numeric ids) must NOT be served — a backtest render is
    deterministic, so the endpoint always regenerates it."""
    from bot.report import snapshot as chart_snapshot

    trades = _run_until_trades(client, seed=42, bars=3000)
    trade = trades[0]
    trade_id = trade["id"]

    stale = chart_snapshot.trade_snapshot_path(int(trade["run_id"]), trade_id, "open")
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_bytes(b"stale-not-a-png")

    resp = client.get(f"/api/trades/{trade_id}/snapshot", params={"at": "open"})
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "image/png"
    # A freshly rendered PNG (magic bytes), never the stale sentinel we planted.
    assert resp.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert resp.content != b"stale-not-a-png"


def test_snapshot_unknown_trade_is_404(client: TestClient) -> None:
    resp = client.get("/api/trades/999999/snapshot", params={"at": "open"})
    assert resp.status_code == 404


def test_snapshot_bad_at_param_is_422(client: TestClient) -> None:
    client.post("/api/run", json={"seed": 42, "bars": 200})
    resp = client.get("/api/trades/1/snapshot", params={"at": "sideways"})
    assert resp.status_code == 422

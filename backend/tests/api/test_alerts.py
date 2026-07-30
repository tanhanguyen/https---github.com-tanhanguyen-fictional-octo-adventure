"""`/api/alerts` (plan 13): the list, the `since_id` cursor, and marking rows read."""

from __future__ import annotations

from bot.alerts.bus import AlertBus
from bot.notify import AlertEvent


def _seed(client, *events: tuple[str, str]) -> None:
    """Write alerts straight through a bus onto the app's own alert connection —
    the same path a runner uses."""
    bus = AlertBus(client.app.state.alerts_conn, notifier=None, run_id=7, source="live")
    for code, title in events:
        bus.emit(AlertEvent(code=code, title=title))


def test_empty_log_is_a_normal_answer(client):
    body = client.get("/api/alerts").json()
    assert body == {"alerts": [], "unread": 0, "max_id": 0}


def test_alerts_are_listed_newest_first_with_their_body(client):
    _seed(client, ("trade_opened", "OPEN BTCUSDT"), ("trade_closed", "CLOSE BTCUSDT"))

    body = client.get("/api/alerts").json()
    assert [a["title"] for a in body["alerts"]] == ["CLOSE BTCUSDT", "OPEN BTCUSDT"]
    assert body["unread"] == 2
    assert body["max_id"] == body["alerts"][0]["id"]
    assert body["alerts"][0]["run_id"] == 7
    assert body["alerts"][0]["source"] == "live"
    assert body["alerts"][0]["level"] == "INFO"


def test_since_id_returns_only_what_is_new(client):
    _seed(client, ("trade_opened", "first"))
    cursor = client.get("/api/alerts").json()["max_id"]

    _seed(client, ("trade_closed", "second"))
    body = client.get("/api/alerts", params={"since_id": cursor}).json()
    assert [a["title"] for a in body["alerts"]] == ["second"]


def test_the_cursor_advances_even_when_a_filter_hides_everything(client):
    """Otherwise a client filtering on CRITICAL would re-scan the same ids forever."""
    _seed(client, ("trade_opened", "an INFO event"))
    body = client.get("/api/alerts", params={"level": "CRITICAL"}).json()
    assert body["alerts"] == []
    assert body["max_id"] > 0


def test_level_filter(client):
    _seed(client, ("trade_opened", "info"), ("feed_degraded", "warn"))
    body = client.get("/api/alerts", params={"level": "WARN"}).json()
    assert [a["title"] for a in body["alerts"]] == ["warn"]


def test_limit_is_bounded(client):
    assert client.get("/api/alerts", params={"limit": 10_000}).status_code == 422


def test_marking_read_is_explicit_and_idempotent(client):
    _seed(client, ("trade_opened", "a"), ("trade_closed", "b"), ("feed_degraded", "c"))
    ids = [a["id"] for a in client.get("/api/alerts").json()["alerts"]][:2]

    body = client.post("/api/alerts/read", json={"ids": ids}).json()
    assert body == {"marked": 2, "unread": 1}

    assert client.post("/api/alerts/read", json={"ids": ids}).json()["unread"] == 1
    assert client.post("/api/alerts/read", json={"ids": []}).json() == {"marked": 0, "unread": 1}

    read_flags = {a["id"]: a["read"] for a in client.get("/api/alerts").json()["alerts"]}
    assert all(read_flags[i] for i in ids)


def test_a_replay_run_produces_alerts_the_dashboard_can_toast(client):
    """Plan 13 definition of done, replay half: stepping the API's runner must land
    trade-lifecycle alerts in the log without Telegram being configured."""
    # BRB's Peak1 -> retest -> breakout-2 -> scoring gate (docs/spec_v2.md) cuts entry
    # frequency by design; fall back to v1.2 single-phase entries so this fixed
    # seed/bar-count window reliably produces a trade -- this test is about the alert
    # plumbing, not the strategy (BRB itself is covered by test_strategies.py /
    # test_main_loop.py).
    assert (
        client.patch(
            "/api/config", json={"strategies": {"breakout": {"require_second_breakout": False}}}
        ).status_code
        == 200
    )
    assert client.post("/api/run", json={"seed": 42, "bars": 300}).status_code == 200
    for _ in range(300):
        client.post("/api/run/step")

    body = client.get("/api/alerts", params={"limit": 500}).json()
    codes = {a["code"] for a in body["alerts"]}
    assert {"trade_pending", "trade_opened", "trade_closed"} <= codes
    assert body["unread"] == len(body["alerts"])
    # No token in the test environment -> nothing was sent, everything was still logged.
    assert all(a["sent_telegram"] is False for a in body["alerts"])
    assert all(a["source"] == "backtest" for a in body["alerts"])

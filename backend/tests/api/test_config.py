from __future__ import annotations

from fastapi.testclient import TestClient


def test_get_config(client: TestClient) -> None:
    resp = client.get("/api/config")
    assert resp.status_code == 200
    body = resp.json()
    assert body["is_active"] is True
    assert body["config"]["symbol"] == "EURUSD"


def test_patch_config_creates_new_active_version(client: TestClient) -> None:
    before = client.get("/api/config").json()
    resp = client.patch("/api/config", json={"filters": {"mtf": {"enabled": False}}})
    assert resp.status_code == 200
    after = resp.json()
    assert after["version"] == before["version"] + 1
    assert after["is_active"] is True
    assert after["config"]["filters"]["mtf"]["enabled"] is False

    versions = client.get("/api/config/versions").json()
    assert len(versions) >= 2


def test_patch_invalid_config_rejected_without_new_version(client: TestClient) -> None:
    before = client.get("/api/config").json()
    resp = client.patch("/api/config", json={"symbol_type": "NOT_A_REAL_TYPE"})
    assert resp.status_code == 422

    after = client.get("/api/config").json()
    assert after["version"] == before["version"]


def test_config_schema(client: TestClient) -> None:
    resp = client.get("/api/config/schema")
    assert resp.status_code == 200
    body = resp.json()
    assert "json_schema" in body
    # 16 filters + `symbols` (plan 04) + `alerts` (plan 13)
    assert len(body["metadata"]) == 18
    assert {m["field"] for m in body["metadata"]} >= {"symbols", "alerts"}
    # Invariant #9: a new config section must arrive in the schema the form renders from.
    assert "alerts" in body["json_schema"]["properties"]


def test_activate_config_version_rollback(client: TestClient) -> None:
    v1 = client.get("/api/config").json()
    client.patch("/api/config", json={"filters": {"mtf": {"enabled": False}}})
    v2 = client.get("/api/config").json()
    assert v2["id"] != v1["id"]

    resp = client.post(f"/api/config/versions/{v1['id']}/activate")
    assert resp.status_code == 200
    active = client.get("/api/config").json()
    assert active["id"] == v1["id"]
    assert active["config"]["filters"]["mtf"]["enabled"] is True

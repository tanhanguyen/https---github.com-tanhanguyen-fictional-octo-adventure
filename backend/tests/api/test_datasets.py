from __future__ import annotations

from fastapi.testclient import TestClient


def test_create_and_list_datasets(client: TestClient) -> None:
    resp = client.post("/api/datasets", json={"seed": 7, "bars": 100})
    assert resp.status_code == 200
    created = resp.json()
    assert created["seed"] == 7

    listed = client.get("/api/datasets").json()
    assert any(d["id"] == created["id"] for d in listed)


def test_symbols(client: TestClient) -> None:
    resp = client.get("/api/symbols")
    assert resp.status_code == 200
    symbols = resp.json()
    assert any(s["symbol"] == "EURUSD" for s in symbols)

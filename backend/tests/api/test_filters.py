from __future__ import annotations

from fastapi.testclient import TestClient


def test_filters_returns_exactly_16_rows(client: TestClient) -> None:
    resp = client.get("/api/filters")
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 16


def test_atr_ref_filter_is_locked(client: TestClient) -> None:
    rows = client.get("/api/filters").json()
    atr_ref = next(r for r in rows if r["id"] == "atr_ref")
    assert atr_ref["locked"] is True

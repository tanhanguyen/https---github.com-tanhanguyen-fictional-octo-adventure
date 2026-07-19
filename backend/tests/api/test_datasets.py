from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "csv" / "eurusd_15m_sample.csv"


def test_create_and_list_datasets(client: TestClient) -> None:
    resp = client.post("/api/datasets", json={"seed": 7, "bars": 100})
    assert resp.status_code == 200
    created = resp.json()
    assert created["seed"] == 7

    listed = client.get("/api/datasets").json()
    assert any(d["id"] == created["id"] for d in listed)


def test_import_csv_dataset(client: TestClient) -> None:
    resp = client.post(
        "/api/datasets/import",
        json={"path": str(FIXTURE), "symbol": "EURUSD", "native_tf": "15m"},
    )
    assert resp.status_code == 200
    created = resp.json()
    assert created["kind"] == "csv"
    assert created["symbol"] == "EURUSD"
    assert created["bar_count"] == 2000

    listed = client.get("/api/datasets").json()
    assert any(d["id"] == created["id"] for d in listed)


def test_import_csv_dataset_bad_data_returns_422(client: TestClient, tmp_path: Path) -> None:
    bad = tmp_path / "bad.csv"
    bad.write_text("open_ts,open,high,low,close,volume\n2024-01-01T00:00:00Z,1,0.5,0.4,1.2,1\n")
    resp = client.post(
        "/api/datasets/import", json={"path": str(bad), "symbol": "EURUSD", "native_tf": "15m"}
    )
    assert resp.status_code == 422


def test_symbols(client: TestClient) -> None:
    resp = client.get("/api/symbols")
    assert resp.status_code == 200
    symbols = resp.json()
    assert any(s["symbol"] == "EURUSD" for s in symbols)

"""Bearer-token gate (plan 09 §2). Token set -> everything but /api/health needs it."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bot.api.app import create_app

TOKEN = "s3cret-token"


@pytest.fixture
def auth_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("BOT_API_TOKEN", TOKEN)
    app = create_app(db_path=str(tmp_path / "test.db"))
    with TestClient(app) as c:
        yield c
    app.state.runner_service.close()


def test_health_is_public(auth_client: TestClient) -> None:
    assert auth_client.get("/api/health").status_code == 200


def test_missing_token_rejected(auth_client: TestClient) -> None:
    resp = auth_client.get("/api/account")
    assert resp.status_code == 401
    assert "token" in resp.json()["detail"].lower()


def test_wrong_token_rejected(auth_client: TestClient) -> None:
    resp = auth_client.get("/api/account", headers={"Authorization": "Bearer nope"})
    assert resp.status_code == 401


def test_valid_token_accepted(auth_client: TestClient) -> None:
    resp = auth_client.get("/api/account", headers={"Authorization": f"Bearer {TOKEN}"})
    assert resp.status_code == 200


def test_no_token_env_is_dev_mode(client: TestClient) -> None:
    # The default fixture sets no BOT_API_TOKEN -> auth middleware not installed.
    assert client.get("/api/account").status_code == 200

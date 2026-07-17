from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bot.api.app import create_app


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    app = create_app(db_path=str(tmp_path / "test.db"))
    with TestClient(app) as c:
        yield c
    app.state.runner_service.close()

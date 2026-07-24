"""FastAPI app factory. Thin router layer over RunnerService — no business logic here."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from bot.alerts.store import connect_alerts_db, default_alerts_db_path
from bot.api.routers import (
    account,
    alerts,
    config,
    datasets,
    decisions,
    equity,
    filters,
    live,
    news,
    run,
    runs,
    trades,
)
from bot.api.run_service import RunnerService, default_db_path


def _alerts_db_for(db_path: str | None) -> str:
    """The alert log lives next to whichever run database this app was pointed at.

    That makes a test app (tmp_path) isolated automatically and keeps the production pair
    (`data/runtime.db` + `data/alerts.db`) in one directory, without a second
    environment variable to remember."""
    if db_path is None:
        return default_alerts_db_path()
    return str(Path(db_path).resolve().with_name("alerts.db"))


def create_app(db_path: str | None = None, alerts_db_path: str | None = None) -> FastAPI:
    app = FastAPI(title="Trading Bot API")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.alerts_conn = connect_alerts_db(alerts_db_path or _alerts_db_for(db_path))
    app.state.runner_service = RunnerService(
        db_path or default_db_path(), alerts_conn=app.state.alerts_conn
    )

    app.include_router(account.router, prefix="/api", tags=["account"])
    app.include_router(config.router, prefix="/api", tags=["config"])
    app.include_router(filters.router, prefix="/api", tags=["filters"])
    app.include_router(trades.router, prefix="/api", tags=["trades"])
    app.include_router(decisions.router, prefix="/api", tags=["decisions"])
    app.include_router(run.router, prefix="/api", tags=["run"])
    app.include_router(runs.router, prefix="/api", tags=["runs"])
    app.include_router(datasets.router, prefix="/api", tags=["datasets"])
    app.include_router(equity.router, prefix="/api", tags=["equity"])
    app.include_router(news.router, prefix="/api", tags=["news"])
    app.include_router(live.router, prefix="/api", tags=["live"])
    app.include_router(alerts.router, prefix="/api", tags=["alerts"])

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()

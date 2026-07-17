"""FastAPI dependency wiring — pulls the single RunnerService instance off app.state."""

from __future__ import annotations

from fastapi import Request

from bot.api.run_service import RunnerService


def get_runner_service(request: Request) -> RunnerService:
    service: RunnerService = request.app.state.runner_service
    return service

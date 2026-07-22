from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from bot.api.deps import get_runner_service
from bot.api.run_service import RunnerService
from bot.api.schemas import NewsEventOut, NewsImportIn, NewsImportOut
from bot.core.errors import ConfigError

router = APIRouter()


@router.post("/news/import", response_model=NewsImportOut)
def import_news(
    body: NewsImportIn, service: RunnerService = Depends(get_runner_service)
) -> NewsImportOut:
    try:
        result = service.import_news(body.path)
    except ConfigError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=422, detail=f"file not found: {body.path}") from exc
    return NewsImportOut(**vars(result))


@router.get("/news", response_model=list[NewsEventOut])
def list_news(
    from_: str | None = Query(None, alias="from"),
    to: str | None = None,
    service: RunnerService = Depends(get_runner_service),
) -> list[NewsEventOut]:
    return [NewsEventOut(**e) for e in service.list_news(from_, to)]

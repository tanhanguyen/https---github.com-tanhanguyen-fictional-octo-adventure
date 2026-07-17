from __future__ import annotations

import json
import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError

from bot.api.deps import get_runner_service
from bot.api.run_service import RunnerService
from bot.api.schemas import ConfigOut, ConfigSchemaOut, ConfigVersionOut, FieldMetaOut
from bot.config.metadata import FILTER_METADATA
from bot.config.models import BotConfig

router = APIRouter()


def _row_to_config_out(row: sqlite3.Row) -> ConfigOut:
    return ConfigOut(
        id=row["id"],
        version=row["version"],
        is_active=bool(row["is_active"]),
        created_at_utc=row["created_at_utc"],
        note=row["note"],
        config=json.loads(row["config_json"]),
    )


@router.get("/config", response_model=ConfigOut)
def get_config(service: RunnerService = Depends(get_runner_service)) -> ConfigOut:
    row, _cfg = service.get_active_config()
    return _row_to_config_out(row)


@router.patch("/config", response_model=ConfigOut)
def patch_config(
    patch: dict[str, Any], service: RunnerService = Depends(get_runner_service)
) -> ConfigOut:
    try:
        row = service.patch_config(patch, note="api patch")
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=json.loads(exc.json())) from exc
    return _row_to_config_out(row)


@router.get("/config/schema", response_model=ConfigSchemaOut)
def get_config_schema() -> ConfigSchemaOut:
    return ConfigSchemaOut(
        json_schema=BotConfig.model_json_schema(),
        metadata=[
            FieldMetaOut(
                field=m.field,
                label_vi=m.label_vi,
                group=m.group,
                ordinal=m.ordinal,
                kind=m.kind.value if m.kind else None,
                locked=m.locked,
                spec_ref=m.spec_ref,
                min=m.min,
                max=m.max,
                step=m.step,
            )
            for m in FILTER_METADATA
        ],
    )


@router.get("/config/versions", response_model=list[ConfigVersionOut])
def list_config_versions(
    service: RunnerService = Depends(get_runner_service),
) -> list[ConfigVersionOut]:
    return [
        ConfigVersionOut(
            id=r["id"],
            version=r["version"],
            is_active=bool(r["is_active"]),
            created_at_utc=r["created_at_utc"],
            note=r["note"],
        )
        for r in service.list_config_versions()
    ]


@router.post("/config/versions/{version_id}/activate", response_model=ConfigOut)
def activate_config_version(
    version_id: int, service: RunnerService = Depends(get_runner_service)
) -> ConfigOut:
    try:
        row = service.activate_config_version(version_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="config version not found") from exc
    return _row_to_config_out(row)

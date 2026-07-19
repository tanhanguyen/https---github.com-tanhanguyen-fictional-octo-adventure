"""Pydantic request/response models for the REST API. No business logic here."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class HealthOut(BaseModel):
    status: str = "ok"


class AccountOut(BaseModel):
    run_id: int | None
    equity: float
    balance: float
    drawdown_pct: float
    open_trades: int
    current_risk_pct: float
    daily_loss_count: int
    daily_losses_remaining: int
    current_trading_day: str | None
    consecutive_wins: int
    consecutive_losses: int
    risk_multiplier: float
    bot_enabled: bool
    blocked_reason: str | None


class ConfigVersionOut(BaseModel):
    id: int
    version: int
    is_active: bool
    created_at_utc: str
    note: str


class ConfigOut(BaseModel):
    id: int
    version: int
    is_active: bool
    created_at_utc: str
    note: str
    config: dict[str, Any]


class FieldMetaOut(BaseModel):
    field: str
    label_vi: str
    group: str
    ordinal: int
    kind: str | None
    locked: bool
    spec_ref: str
    min: float | None
    max: float | None
    step: float | None


class ConfigSchemaOut(BaseModel):
    json_schema: dict[str, Any]
    metadata: list[FieldMetaOut]


class FilterRowOut(BaseModel):
    id: str
    label_vi: str
    kind: str
    enabled: bool
    locked: bool
    params: dict[str, Any]
    last_evaluation: dict[str, Any] | None = None


class TradeEventOut(BaseModel):
    id: int
    event_type: str
    ts_utc: str
    price: float | None
    detail: str | None


class TradeOut(BaseModel):
    id: int
    run_id: int
    symbol: str
    strategy: str
    direction: str
    status: str
    entry_price: float | None
    sl_price: float | None
    tp1_price: float | None
    tp2_price: float | None
    lot_size: float | None
    opened_at_utc: str | None
    closed_at_utc: str | None
    trading_day: str | None
    result: str | None
    pnl_amount: float | None
    pnl_r: float | None
    decision_id: int | None


class TradeDetailOut(TradeOut):
    trade_events: list[TradeEventOut]


class DecisionOut(BaseModel):
    id: int
    run_id: int
    bar_ts_utc: str
    reason: str
    stage: str
    detail: str | None
    strategy: str | None
    direction: str | None
    trade_id: int | None


class DecisionFilterOut(BaseModel):
    id: int
    filter_id: str
    kind: str
    enabled: bool
    evaluated: bool
    passed: bool | None
    blocking: bool
    values: dict[str, Any]
    detail: str | None


class DecisionDetailOut(DecisionOut):
    filters: list[DecisionFilterOut]


class DecisionStatsOut(BaseModel):
    histogram: dict[str, int]


class EquityPointOut(BaseModel):
    bar_ts_utc: str
    equity: float
    balance: float


class SymbolOut(BaseModel):
    symbol: str
    symbol_type: str


class DatasetCreateIn(BaseModel):
    seed: int = 42
    bars: int = 5000


class DatasetImportIn(BaseModel):
    path: str
    symbol: str
    native_tf: str = "15m"


class DatasetOut(BaseModel):
    id: str
    kind: str = "synthetic"
    created_at_utc: str
    # synthetic-only
    seed: int | None = None
    n_candles_15m: int | None = None
    # csv-only
    symbol: str | None = None
    native_tf: str | None = None
    source_path: str | None = None
    file_sha256: str | None = None
    start_ts: str | None = None
    end_ts: str | None = None
    bar_count: int | None = None
    gap_count: int | None = None


class RunOut(BaseModel):
    id: int
    dataset_id: str
    config_version_id: int
    symbol: str
    status: str
    starting_equity: float
    created_at_utc: str
    is_playing: bool


class RunCreateIn(BaseModel):
    seed: int = 42
    bars: int = 5000
    dataset_id: str | None = None


class RunStepOut(BaseModel):
    bar_ts: str
    reason: str
    stage: str
    trade_event_types: list[str]
    closed_result: str | None
    equity: float
    exhausted: bool = False


class PlayIn(BaseModel):
    interval_ms: int = 200

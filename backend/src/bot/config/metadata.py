"""Per-field UI metadata (label_vi, group, ordinal, kind, locked, spec_ref, min/max/step).

Consumed later by /api/config/schema (Phase 4) so FilterConfigPanel can render the whole
form without frontend changes when a new filter is added. Built now per the Phase-2 plan.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from bot.core.types import FilterKind


@dataclass(frozen=True)
class FieldMeta:
    field: str  # dotted path e.g. "filters.adx_filter.threshold_trend"
    label_vi: str
    group: str
    ordinal: int
    kind: Optional[FilterKind]
    locked: bool = False
    spec_ref: str = ""
    min: Optional[float] = None
    max: Optional[float] = None
    step: Optional[float] = None


FILTER_METADATA: list[FieldMeta] = [
    FieldMeta(
        "filters.trend", "Xu hướng chính (EMA34/89)", "regime", 1, FilterKind.REGIME,
        spec_ref="§2#1, §3",
    ),
    FieldMeta(
        "filters.adx_filter", "Cường độ xu hướng (ADX)", "regime", 2, FilterKind.REGIME,
        spec_ref="§2#2",
    ),
    FieldMeta(
        "filters.er_filter", "Độ mượt xu hướng (ER)", "regime", 3, FilterKind.REGIME,
        spec_ref="§2#3, §6.3",
    ),
    FieldMeta(
        "filters.atr_ref", "Biến động tham chiếu (ATR)", "input", 4, FilterKind.INPUT,
        locked=True, spec_ref="§2#4",
    ),
    FieldMeta(
        "filters.atr_zscore", "Biến động tương đối (ATR Z-score)", "modifier", 5,
        FilterKind.MODIFIER, spec_ref="§2#5, §6.4",
    ),
    FieldMeta(
        "filters.volume", "Khối lượng (Volume)", "gate", 6, FilterKind.GATE,
        spec_ref="§2#6",
    ),
    FieldMeta(
        "filters.session", "Lọc thời gian (Session)", "gate", 7, FilterKind.GATE,
        spec_ref="§2#7",
    ),
    FieldMeta(
        "filters.mtf", "Lọc đa khung thời gian (MTF)", "gate", 8, FilterKind.GATE,
        spec_ref="§2#8, §6.5",
    ),
    FieldMeta(
        "filters.dxy", "Lọc tương quan DXY", "gate", 9, FilterKind.GATE,
        spec_ref="§2#9, §6.6",
    ),
    FieldMeta(
        "filters.confirmation_lag", "Trễ pha xác nhận", "gate", 10, FilterKind.GATE,
        spec_ref="§2#10, §6.1",
    ),
    FieldMeta(
        "filters.equity_curve", "Trạng thái tài khoản (Equity Curve)", "modifier", 11,
        FilterKind.MODIFIER, spec_ref="§2#11, §6.2",
    ),
    FieldMeta(
        "filters.time_stop", "Thời gian sống của lệnh (Time Stop)", "exit", 12,
        FilterKind.EXIT, spec_ref="§2#12",
    ),
    FieldMeta(
        "filters.range_width", "Lọc biến động giá thấp (Range Width)", "gate", 13,
        FilterKind.GATE, spec_ref="§2#13",
    ),
    FieldMeta(
        "filters.account_risk", "Giới hạn rủi ro cấp tài khoản", "gate", 14, FilterKind.GATE,
        spec_ref="§2#14, §6.7",
    ),
    FieldMeta(
        "filters.wick", "Nến rút chân (Wick)", "gate", 15, FilterKind.GATE,
        spec_ref="D4 (không có số trong spec)",
    ),
    FieldMeta(
        "filters.news", "Lọc tin tức (News)", "gate", 16, FilterKind.GATE,
        spec_ref="§8 bước 3, tách khỏi session",
    ),
]


def metadata_by_field() -> dict[str, FieldMeta]:
    return {m.field: m for m in FILTER_METADATA}

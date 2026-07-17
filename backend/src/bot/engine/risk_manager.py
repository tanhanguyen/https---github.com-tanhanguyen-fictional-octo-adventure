"""Position sizing (pure). C7: risk % = MAX_RISK_PER_TRADE x risk_multiplier, no hardcoded 1.0."""

from __future__ import annotations

import math
from dataclasses import dataclass

from bot.core.types import InstrumentSpec


@dataclass(frozen=True)
class LotSizeResult:
    lot: float
    risk_amount: float
    realized_risk_amount: float


def calculate_lot(
    equity: float,
    max_risk_per_trade_pct: float,
    risk_multiplier: float,
    sl_distance: float,
    instrument: InstrumentSpec,
) -> LotSizeResult:
    """Risk amount = equity * (max_risk_per_trade_pct/100) * risk_multiplier (C7).
    Lot is rounded DOWN to instrument.lot_step so realized risk never exceeds target
    by more than one lot-step's worth."""
    if sl_distance <= 0 or equity <= 0:
        return LotSizeResult(lot=0.0, risk_amount=0.0, realized_risk_amount=0.0)

    risk_amount = equity * (max_risk_per_trade_pct / 100.0) * risk_multiplier
    pips = sl_distance / instrument.pip
    value_per_pip_per_lot = instrument.pip_value_per_lot
    if pips <= 0 or value_per_pip_per_lot <= 0:
        return LotSizeResult(lot=0.0, risk_amount=risk_amount, realized_risk_amount=0.0)

    raw_lot = risk_amount / (pips * value_per_pip_per_lot)
    steps = math.floor(raw_lot / instrument.lot_step + 1e-9)
    lot = round(steps * instrument.lot_step, 10)

    if lot < instrument.min_lot:
        return LotSizeResult(lot=0.0, risk_amount=risk_amount, realized_risk_amount=0.0)

    realized = lot * pips * value_per_pip_per_lot
    return LotSizeResult(lot=lot, risk_amount=risk_amount, realized_risk_amount=realized)

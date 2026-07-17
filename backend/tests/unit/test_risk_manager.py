from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from bot.core.types import InstrumentSpec
from bot.engine.risk_manager import calculate_lot

EURUSD = InstrumentSpec(
    symbol="EURUSD",
    contract_size=100_000,
    pip=0.0001,
    pip_value_per_lot=10.0,
    spread_pips=0.0,
    min_lot=0.01,
    lot_step=0.01,
)


@given(
    equity=st.floats(min_value=1000, max_value=1_000_000, allow_nan=False, allow_infinity=False),
    sl_distance_pips=st.floats(
        min_value=1.0, max_value=500.0, allow_nan=False, allow_infinity=False
    ),
    risk_multiplier=st.sampled_from([1.0, 0.5, 0.3]),
)
@settings(max_examples=200)
def test_realized_risk_within_one_lot_step_of_target(equity, sl_distance_pips, risk_multiplier):
    sl_distance = sl_distance_pips * EURUSD.pip
    result = calculate_lot(
        equity=equity,
        max_risk_per_trade_pct=1.0,
        risk_multiplier=risk_multiplier,
        sl_distance=sl_distance,
        instrument=EURUSD,
    )
    if result.lot == 0.0:
        # Too small to open even a min_lot position -- risk amount must have been
        # below the value of one min_lot trade.
        min_lot_risk = EURUSD.min_lot * sl_distance_pips * EURUSD.pip_value_per_lot
        assert result.risk_amount < min_lot_risk + 1e-6
        return

    one_lot_step_risk = EURUSD.lot_step * sl_distance_pips * EURUSD.pip_value_per_lot
    assert result.realized_risk_amount <= result.risk_amount + 1e-6
    assert result.risk_amount - result.realized_risk_amount <= one_lot_step_risk + 1e-6


def test_zero_sl_distance_yields_zero_lot():
    result = calculate_lot(
        equity=10_000,
        max_risk_per_trade_pct=1.0,
        risk_multiplier=1.0,
        sl_distance=0.0,
        instrument=EURUSD,
    )
    assert result.lot == 0.0


def test_c7_uses_config_risk_not_hardcoded_one():
    r1 = calculate_lot(
        equity=10_000,
        max_risk_per_trade_pct=2.0,
        risk_multiplier=1.0,
        sl_distance=0.0020,
        instrument=EURUSD,
    )
    r2 = calculate_lot(
        equity=10_000,
        max_risk_per_trade_pct=1.0,
        risk_multiplier=1.0,
        sl_distance=0.0020,
        instrument=EURUSD,
    )
    assert r1.risk_amount == 2 * r2.risk_amount

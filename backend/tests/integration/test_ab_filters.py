"""A/B filter harness (plans/01-stabilize.md): proves toggling a filter actually
changes bot behavior on synthetic data -- no dead/no-op filter toggles among the
ones expected to fire reliably at these seed/bars."""

from __future__ import annotations

import pytest

from bot.cli import _AB_EXCLUDED_FILTERS, _AB_MAY_BE_INERT, _build_instrument, _run
from bot.config.loader import load_default_config, load_instruments
from bot.data.dataset import DatasetSpec, generate_bundle
from bot.data.feed import Feed
from bot.filters.registry import ALL_FILTER_IDS

pytestmark = pytest.mark.slow

BARS = 5000
SEED = 42

# Filters the plan requires to reliably change the decision stream on toggle at
# this seed/bars (docs/decisions.md, tech-debt/A-B harness section). mtf is excluded --
# empirically inert at seed=42/bars=5000 (see _AB_MAY_BE_INERT in bot.cli and
# docs/decisions.md), same class of rarity as MR's 3-condition AND. confirmation_lag
# moved to may-be-inert 2026-07-19: it no longer applies to BREAKOUT signals.
_MUST_CHANGE = {"session", "adx_filter", "er_filter", "trend"}


def _setup():
    config = load_default_config()
    instrument = _build_instrument(config, load_instruments())
    n_candles_15m = (BARS + 400) * 4
    dataset_spec = DatasetSpec(
        seed=SEED,
        n_candles_15m=n_candles_15m,
        symbol=config.symbol,
        rollover_tz=config.trading_day_rollover_tz,
        rollover_time=config.trading_day_rollover_time,
    )
    bundle = generate_bundle(dataset_spec)
    price_feed = Feed(frames=bundle["price"])
    dxy_feed = Feed(frames=bundle["dxy"])
    return config, instrument, price_feed, dxy_feed


def test_ab_no_unexplained_dead_filters():
    config, instrument, price_feed, dxy_feed = _setup()
    baseline = _run("ab-test-baseline", config, instrument, price_feed, dxy_feed, BARS)

    must_change_confirmed = set()
    unexplained_dead = []
    for fid in ALL_FILTER_IDS:
        if fid in _AB_EXCLUDED_FILTERS:
            continue
        variant = config.model_copy(deep=True)
        toggle = getattr(variant.filters, fid)
        toggle.enabled = not toggle.enabled
        result = _run(f"ab-test-{fid}", variant, instrument, price_feed, dxy_feed, BARS)

        changed = result.decision_hash != baseline.decision_hash
        if changed and fid in _MUST_CHANGE:
            must_change_confirmed.add(fid)
        if not changed and fid not in _AB_MAY_BE_INERT:
            unexplained_dead.append(fid)

    assert unexplained_dead == []
    missing = _MUST_CHANGE - must_change_confirmed
    assert missing == set(), f"filters expected to change the decision stream did not: {missing}"

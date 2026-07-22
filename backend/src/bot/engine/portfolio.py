"""Plan 04: shared portfolio construction — turns `BotConfig.symbols` into the
`dict[str, SymbolContext]` + shared DXY feed the multi-symbol `Runner` needs. Used by
both the CLI (`bot.cli`) and the API (`bot.api.run_service`) for the synthetic-data path.

DXY (shared macro series, not per-symbol): reused from the alphabetically-first enabled
FOREX symbol's own generated bundle (its `dxy` frames, already correlated to that symbol's
price series) -- no separate anchor dataset. Symbols with no enabled FOREX entry get no
DXY feed (matches `dxy` filter only ever being consulted when `symbol_type == "FOREX"`,
see `bot/engine/context.py::build_context`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from bot.config.models import BotConfig, effective_config_for_symbol
from bot.core.types import InstrumentSpec
from bot.data.dataset import DatasetSpec, generate_bundle, named_child_seed
from bot.data.feed import Feed
from bot.engine.context import SymbolContext, build_symbol_context


@dataclass
class PortfolioBundle:
    symbols: dict[str, SymbolContext]
    dxy_feed: Feed | None
    dataset_seeds: dict[str, int]  # symbol -> derived seed actually used (informational)


def _instrument_from_yaml(
    symbol: str, instruments_yaml: dict[str, dict[str, Any]]
) -> InstrumentSpec:
    spec = instruments_yaml.get(symbol)
    if spec is None:
        raise KeyError(f"no instrument spec for symbol {symbol!r}")
    return InstrumentSpec(
        symbol=spec["symbol"],
        contract_size=spec["contract_size"],
        pip=spec["pip"],
        pip_value_per_lot=spec["pip_value_per_lot"],
        spread_pips=spec["spread_pips"],
        min_lot=spec["min_lot"],
        lot_step=spec["lot_step"],
        currencies=tuple(spec.get("currencies", ())),
    )


def build_portfolio_from_synthetic(
    config: BotConfig,
    instruments_yaml: dict[str, dict[str, Any]],
    base_seed: int,
    n_candles_15m: int,
) -> PortfolioBundle:
    """Generates one synthetic dataset per enabled symbol and builds each symbol's
    `SymbolContext`. Dataset seed: an auto-migrated single-symbol config (the common,
    backward-compat case) uses `base_seed` directly, byte-identical to pre-plan-04
    behavior -- named_child_seed only kicks in once there is more than one enabled
    symbol, where it prevents adding a new symbol from perturbing another's stream
    (see `bot.data.dataset.named_child_seed`)."""
    enabled = sorted((e for e in config.symbols if e.enabled), key=lambda e: e.symbol)
    if not enabled:
        raise ValueError("no enabled symbols in config.symbols")

    symbols: dict[str, SymbolContext] = {}
    dataset_seeds: dict[str, int] = {}
    dxy_frames = None
    for entry in enabled:
        eff_cfg = effective_config_for_symbol(config, entry)
        if entry.dataset_seed is not None:
            seed = entry.dataset_seed
        elif len(enabled) == 1:
            seed = base_seed
        else:
            seed = named_child_seed(base_seed, entry.symbol)
        dataset_seeds[entry.symbol] = seed
        start_price = instruments_yaml.get(entry.symbol, {}).get("synthetic_start_price", 1.1000)
        spec = DatasetSpec(
            seed=seed,
            n_candles_15m=n_candles_15m,
            start_price=start_price,
            symbol=entry.symbol,
            rollover_tz=eff_cfg.trading_day_rollover_tz,
            rollover_time=eff_cfg.trading_day_rollover_time,
        )
        bundle = generate_bundle(spec)
        price_feed = Feed(frames=bundle["price"])
        if dxy_frames is None and eff_cfg.symbol_type == "FOREX":
            dxy_frames = bundle["dxy"]
        instrument = _instrument_from_yaml(entry.symbol, instruments_yaml)
        symbols[entry.symbol] = build_symbol_context(eff_cfg, price_feed, instrument)

    dxy_feed = Feed(frames=dxy_frames) if dxy_frames is not None else None
    return PortfolioBundle(symbols=symbols, dxy_feed=dxy_feed, dataset_seeds=dataset_seeds)

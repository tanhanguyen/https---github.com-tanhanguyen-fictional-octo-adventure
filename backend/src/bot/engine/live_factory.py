"""Wiring a live paper-trading session: config + venue feeds + DB run -> LiveRunner.

Two safety rules from plan 07 §3 live here:

* **A live run gets its own DB** (`backend/data/live.db`, overridable with
  `BOT_DB_PATH`), so fiddling with live never corrupts backtest history — and vice
  versa.
* **The config is snapshotted at run creation and then frozen.** Changing config means
  stopping and starting a new live run; there is no hot reload. That is the boring,
  safe option: a run's decisions can always be replayed from exactly one config version.

One process runs the WHOLE portfolio (plan 07 §2, re-checked 2026-07-18):
`MAX_CONCURRENT_TRADES`, the daily-loss limit and `max_total_open_risk_pct` are
account-wide, so one process per symbol would quietly disable every portfolio-level cap.
`--symbol` exists only as a debug override for running one symbol alone.
"""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bot.config.loader import load_default_config, load_instruments
from bot.config.models import BotConfig, live_effective_config
from bot.config.profiles import is_stock_vn
from bot.core.errors import ConfigError
from bot.core.types import InstrumentSpec
from bot.core.wallclock import NowFn, utc_now
from bot.data.dnse_feed import DNSE_OPENAPI_BASE, DnseOhlcFeed, market_type_for
from bot.data.feed import Feed
from bot.data.live_feed import BINANCE_FUTURES_MAINNET, BinanceFuturesFeed
from bot.data.live_feed import empty_frame as _empty_frame
from bot.db import repositories as repo
from bot.db.connection import connect_and_migrate
from bot.engine.context import build_symbol_context
from bot.engine.live_runner import BarSource, LiveRunner, LiveSymbol
from bot.notify import LiveAlerts, Notifier, build_notifier

#: Venues that can serve a live feed today: Binance USDⓈ-M Futures for CRYPTO (plan 07)
#: and the DNSE OpenAPI OHLC history for both Vietnamese spot and derivatives. FOREX is
#: still plan 10 — nothing here serves it, so it is refused up front.
SUPPORTED_LIVE_SYMBOL_TYPES = {"CRYPTO", "STOCK_VN_CASH", "STOCK_VN_DERIV"}


def default_live_db_path() -> str:
    env = os.environ.get("BOT_DB_PATH")
    if env:
        return env
    backend_root = Path(__file__).resolve().parents[3]
    data_dir = backend_root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return str(data_dir / "live.db")


def _instrument(symbol: str, instruments_yaml: dict[str, Any]) -> InstrumentSpec:
    spec = instruments_yaml.get(symbol)
    if spec is None:
        raise ConfigError(f"no instrument spec for symbol {symbol!r}")
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


@dataclass
class LiveSession:
    conn: sqlite3.Connection
    run_id: int
    runner: LiveRunner
    resumed: bool
    config: BotConfig

    def close(self) -> None:
        self.conn.close()


def build_live_session(
    db_path: str | None = None,
    only_symbol: str | None = None,
    base_url: str = BINANCE_FUTURES_MAINNET,
    config: BotConfig | None = None,
    source_factory: Any | None = None,
    notifier: Notifier | None = None,
    now_fn: NowFn = utc_now,
    sleep_fn: Any | None = None,
    conn: sqlite3.Connection | None = None,
) -> LiveSession:
    """Create (or resume) the live run and return a ready-to-run LiveRunner.

    Resume path: an existing RUNNING `mode='live'` run is reused together with its
    frozen config version, so a restart never silently picks up an edited config."""
    if conn is not None:
        connection = conn
    else:
        connection = connect_and_migrate(db_path or default_live_db_path())

    cfg_version_id: int | None = None
    existing = repo.find_active_live_run(connection)
    if existing is not None:
        cfg_row = connection.execute(
            "SELECT * FROM config_version WHERE id=?", (existing["config_version_id"],)
        ).fetchone()
        if cfg_row is None:
            raise ConfigError(
                f"live run {existing['id']} references a missing config version "
                f"{existing['config_version_id']}"
            )
        cfg = BotConfig.model_validate_json(cfg_row["config_json"])
        run_id = int(existing["id"])
        resumed = True
        # A stop that was requested while the process was down must not be lost, but it
        # also must not immediately kill a deliberate restart: clearing it here means
        # "stop" is always an explicit, current instruction.
        repo.request_stop(connection, run_id, False)
    else:
        cfg = config if config is not None else load_default_config()
        cfg_version_id = repo.create_config_version(
            connection, cfg.model_dump_json(), note="live run snapshot"
        )
        run_id = 0  # assigned below, once the symbol/dataset list is known
        resumed = False

    entries = [e for e in cfg.symbols if e.enabled]
    if only_symbol is not None:
        entries = [e for e in entries if e.symbol == only_symbol]
    if not entries:
        raise ConfigError(
            "no enabled symbols to run live"
            + (f" (filtered by --symbol {only_symbol!r})" if only_symbol else "")
        )

    instruments_yaml = load_instruments()
    symbols: dict[str, LiveSymbol] = {}
    symbol_datasets: dict[str, str] = {}

    for entry in sorted(entries, key=lambda e: e.symbol):
        eff_cfg = live_effective_config(cfg, entry)
        if eff_cfg.symbol_type not in SUPPORTED_LIVE_SYMBOL_TYPES:
            raise ConfigError(
                f"{entry.symbol}: live feed for symbol_type {eff_cfg.symbol_type!r} is "
                "not implemented — CRYPTO runs on Binance USDⓈ-M Futures and "
                "STOCK_VN_CASH / STOCK_VN_DERIV on the DNSE OpenAPI OHLC history; "
                "forex is plan 10"
            )
        source: BarSource
        if source_factory is not None:
            source = source_factory(entry.symbol, eff_cfg.timeframe)
        elif is_stock_vn(eff_cfg.symbol_type):
            source = DnseOhlcFeed(
                entry.symbol,
                eff_cfg.timeframe,
                market_type_for(eff_cfg.symbol_type),
            )
        else:
            source = BinanceFuturesFeed(entry.symbol, eff_cfg.timeframe, base_url=base_url)
        context = build_symbol_context(
            eff_cfg,
            # Starts empty; LiveRunner.start() backfills and resamples into this Feed.
            Feed(frames={eff_cfg.timeframe: _empty_frame()}),
            _instrument(entry.symbol, instruments_yaml),
            cursor=now_fn(),
        )
        symbols[entry.symbol] = LiveSymbol(context=context, source=source)
        # The dataset id encodes the venue so the resume path below can refuse a silent
        # venue swap; VN symbols never come from `base_url` (which is Binance's).
        venue = DNSE_OPENAPI_BASE if is_stock_vn(eff_cfg.symbol_type) else base_url
        symbol_datasets[entry.symbol] = f"live:{venue}:{entry.symbol}:{eff_cfg.timeframe}"

    if resumed:
        # Refuse a venue swap on restart. The dataset id encodes venue/symbol/timeframe,
        # so restarting a mainnet run with --testnet (or vice versa) would keep the
        # equity curve and open positions while the prices underneath them changed. That
        # is exactly the kind of silent mismatch a live run must not survive.
        stored = repo.get_run_symbol_datasets(connection, run_id)
        changed = {
            sym: (stored[sym], did)
            for sym, did in symbol_datasets.items()
            if sym in stored and stored[sym] != did
        }
        if changed:
            raise ConfigError(
                f"live run {run_id} was started against a different feed: "
                + "; ".join(f"{s}: {was!r} -> {now!r}" for s, (was, now) in changed.items())
                + " — stop the run before switching venue or timeframe"
            )
    else:
        assert cfg_version_id is not None
        for sym, did in symbol_datasets.items():
            repo.upsert_live_dataset(
                connection, did, sym, symbols[sym].context.effective_config.timeframe
            )
        run_id = repo.create_run(
            connection, cfg_version_id, symbol_datasets, cfg.starting_equity, mode="live"
        )

    alerts = LiveAlerts(
        notifier if notifier is not None else build_notifier(), run_label=f"live#{run_id}"
    )
    runner = LiveRunner(
        connection,
        run_id,
        symbols,
        cfg,
        alerts,
        now_fn=now_fn,
        sleep_fn=sleep_fn,
    )
    return LiveSession(conn=connection, run_id=run_id, runner=runner, resumed=resumed, config=cfg)

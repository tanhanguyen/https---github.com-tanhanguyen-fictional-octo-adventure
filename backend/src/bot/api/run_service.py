"""RunnerService: thread-safe orchestration of engine/runner.py for the API.

No business logic lives here — it wires config/dataset/feed/Runner together (the same
way cli.py does for `replay`) and exposes step/play/pause/reset behind a lock. Plan:
step-synchronous by default; "play" is a background worker thread holding the lock so
step/play/pause/reset never race.
"""

from __future__ import annotations

import functools
import json
import sqlite3
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any, TypeVar

import pandas as pd

from bot.analytics.metrics import RunReport, compute_run_report, diff_histograms, diff_reports
from bot.config.loader import deep_merge, load_default_config, load_instruments
from bot.config.metadata import metadata_by_field
from bot.config.models import BotConfig, effective_config_for_symbol
from bot.core.clock import Clock
from bot.core.errors import ConfigError
from bot.core.timeframes import TF_DURATION, tf_rank
from bot.core.types import InstrumentSpec
from bot.data.dataset import (
    CsvImportResult,
    DatasetSpec,
    import_csv_dataset,
    load_bundle_for_dataset,
    named_child_seed,
)
from bot.data.dataset import dataset_id as compute_dataset_id
from bot.data.feed import Feed
from bot.db import repositories as repo
from bot.db.connection import migrate
from bot.engine.context import SymbolContext, build_symbol_context
from bot.engine.runner import Runner, StepSummary
from bot.filters.registry import ALL_FILTER_IDS

_R = TypeVar("_R")

#: How many (dataset, config-version) price bundles `_price_frames` keeps resident.
_BARS_CACHE_MAX = 4


def _locked(fn: Callable[..., _R]) -> Callable[..., _R]:
    """Serialize a method against the shared sqlite connection via self.lock.

    The single sqlite3.Connection is shared by the play worker thread and the
    request-handler threads. Using one connection concurrently from multiple
    threads corrupts it ("database disk image is malformed"), so every method
    that touches self.conn must hold self.lock. It is an RLock, so nesting
    (e.g. create_run -> get_active_config) is safe.
    """

    @functools.wraps(fn)
    def wrapper(self: RunnerService, *args: Any, **kwargs: Any) -> _R:
        with self.lock:
            return fn(self, *args, **kwargs)

    return wrapper


def default_db_path() -> str:
    backend_root = Path(__file__).resolve().parents[3]
    data_dir = backend_root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return str(data_dir / "runtime.db")


class RunnerService:
    def __init__(self, db_path: str) -> None:
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        migrate(self.conn)

        self.lock = threading.RLock()
        self.instruments_yaml = load_instruments()

        self.run_id: int | None = None
        self.runner: Runner | None = None
        self.symbol_datasets_active: dict[str, str] | None = None
        self.config_version_id: int | None = None

        self._play_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._bars_cache: OrderedDict[tuple[str, int], dict[str, pd.DataFrame]] = OrderedDict()

        self._ensure_active_config()

    def close(self) -> None:
        with self.lock:
            self._stop_play_locked()
        self.conn.close()

    # ---------------------------------------------------------------- config
    def _ensure_active_config(self) -> int:
        row = repo.get_active_config_version(self.conn)
        if row is not None:
            return int(row["id"])
        cfg = load_default_config()
        return repo.create_config_version(self.conn, cfg.model_dump_json(), note="seed default")

    @_locked
    def get_active_config(self) -> tuple[sqlite3.Row, BotConfig]:
        row = repo.get_active_config_version(self.conn)
        if row is None:
            raise ConfigError("no active config version")
        cfg = BotConfig.model_validate_json(row["config_json"])
        return row, cfg

    @_locked
    def patch_config(self, patch: dict[str, Any], note: str = "") -> sqlite3.Row:
        row, _cfg = self.get_active_config()
        base = json.loads(row["config_json"])
        merged = deep_merge(base, patch)
        new_cfg = BotConfig.model_validate(merged)  # raises pydantic.ValidationError on bad input
        repo.create_config_version(self.conn, new_cfg.model_dump_json(), note=note)
        row2 = repo.get_active_config_version(self.conn)
        assert row2 is not None
        return row2

    @_locked
    def list_config_versions(self) -> list[sqlite3.Row]:
        cur = self.conn.execute("SELECT * FROM config_version ORDER BY version DESC")
        return list(cur.fetchall())

    @_locked
    def activate_config_version(self, config_version_id: int) -> sqlite3.Row:
        cur = self.conn.execute("SELECT id FROM config_version WHERE id=?", (config_version_id,))
        if cur.fetchone() is None:
            raise KeyError(config_version_id)
        repo.activate_config_version(self.conn, config_version_id)
        row = repo.get_active_config_version(self.conn)
        assert row is not None
        return row

    # --------------------------------------------------------------- filters
    @_locked
    def filters_snapshot(self) -> list[dict[str, Any]]:
        _, cfg = self.get_active_config()
        meta = metadata_by_field()
        rows: list[dict[str, Any]] = []
        for fid in ALL_FILTER_IDS:
            m = meta.get(f"filters.{fid}")
            filt_cfg = getattr(cfg.filters, fid)
            params = filt_cfg.model_dump()
            enabled = bool(params.pop("enabled", True))
            locked = bool(params.pop("locked", False)) or (m.locked if m else False)
            rows.append(
                {
                    "id": fid,
                    "label_vi": m.label_vi if m else fid,
                    "kind": cfg.filters.kind_of(fid).value,
                    "enabled": enabled,
                    "locked": locked,
                    "params": params,
                    "last_evaluation": self._last_evaluation(fid),
                }
            )
        return rows

    def _last_evaluation(self, filter_id: str) -> dict[str, Any] | None:
        if self.run_id is None:
            return None
        cur = self.conn.execute(
            "SELECT df.* FROM decision_filter df JOIN decision d ON df.decision_id = d.id "
            "WHERE d.run_id=? AND df.filter_id=? ORDER BY df.id DESC LIMIT 1",
            (self.run_id, filter_id),
        )
        r = cur.fetchone()
        if r is None:
            return None
        return {
            "enabled": bool(r["enabled"]),
            "evaluated": bool(r["evaluated"]),
            "passed": None if r["passed"] is None else bool(r["passed"]),
            "blocking": bool(r["blocking"]),
            "values": json.loads(r["values_json"]) if r["values_json"] else {},
            "detail": r["detail"],
        }

    # -------------------------------------------------------------- datasets
    @_locked
    def create_dataset(
        self,
        seed: int,
        bars: int,
        symbol: str,
        rollover_tz: str,
        rollover_time: str,
        start_price: float = 1.1000,
    ) -> str:
        n_candles_15m = (bars + 400) * 4
        spec = DatasetSpec(
            seed=seed,
            n_candles_15m=n_candles_15m,
            start_price=start_price,
            symbol=symbol,
            rollover_tz=rollover_tz,
            rollover_time=rollover_time,
        )
        did = compute_dataset_id(spec)
        repo.upsert_dataset(self.conn, did, json.dumps(asdict(spec)))
        return did

    @_locked
    def list_datasets(self) -> list[dict[str, Any]]:
        cur = self.conn.execute("SELECT * FROM dataset ORDER BY created_at_utc DESC")
        out: list[dict[str, Any]] = []
        for row in cur.fetchall():
            kind = row["kind"] if row["kind"] else "synthetic"
            if kind == "synthetic":
                spec = json.loads(row["spec_json"])
                out.append(
                    {
                        "id": row["id"],
                        "kind": kind,
                        "seed": spec["seed"],
                        "n_candles_15m": spec["n_candles_15m"],
                        "created_at_utc": row["created_at_utc"],
                    }
                )
            else:
                out.append(
                    {
                        "id": row["id"],
                        "kind": kind,
                        "symbol": row["symbol"],
                        "native_tf": row["native_tf"],
                        "source_path": row["source_path"],
                        "file_sha256": row["file_sha256"],
                        "start_ts": row["start_ts"],
                        "end_ts": row["end_ts"],
                        "bar_count": row["bar_count"],
                        "gap_count": row["gap_count"],
                        "created_at_utc": row["created_at_utc"],
                    }
                )
        return out

    @_locked
    def import_csv(self, path: str, symbol: str, native_tf: str) -> CsvImportResult:
        _, cfg = self.get_active_config()
        result = import_csv_dataset(
            self.conn,
            Path(path),
            symbol,
            native_tf,
            cfg.trading_day_rollover_tz,
            cfg.trading_day_rollover_time,
        )
        # Re-importing can replace the bars behind an existing dataset id.
        self._invalidate_bars_cache(result.dataset_id)
        return result

    # ------------------------------------------------------------- run/step
    def _build_instrument(self, symbol: str) -> InstrumentSpec:
        spec = self.instruments_yaml.get(symbol)
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
        )

    def create_run(
        self, seed: int = 42, bars: int = 5000, dataset_id: str | None = None
    ) -> dict[str, Any]:
        with self.lock:
            self._stop_play_locked()
            cfg_row, cfg = self.get_active_config()
            enabled = [e for e in cfg.symbols if e.enabled]
            if not enabled:
                raise ConfigError("no enabled symbols in config.symbols")

            # `dataset_id` (an explicit, pre-registered dataset -- e.g. imported CSV)
            # only makes sense for a single-symbol config; multi-symbol portfolios
            # always auto-generate one named-child-seeded synthetic dataset per symbol
            # (plan 04 scope -- real per-symbol CSV portfolios are plan 05/07).
            single_legacy = len(enabled) == 1 and dataset_id is not None

            symbol_contexts: dict[str, SymbolContext] = {}
            symbol_datasets: dict[str, str] = {}
            dxy_frames = None

            for entry in sorted(enabled, key=lambda e: e.symbol):
                eff_cfg = effective_config_for_symbol(cfg, entry)
                instrument = self._build_instrument(entry.symbol)

                if single_legacy:
                    assert dataset_id is not None
                    row = repo.get_dataset(self.conn, dataset_id)
                    if row is None:
                        raise KeyError(dataset_id)
                    if row["kind"] == "csv" and tf_rank(row["native_tf"]) > tf_rank(
                        eff_cfg.timeframe
                    ):
                        raise ConfigError(
                            f"dataset native_tf {row['native_tf']!r} is coarser than "
                            f"config.timeframe {eff_cfg.timeframe!r} -- pick a "
                            "finer-or-equal timeframe"
                        )
                    bundle = load_bundle_for_dataset(self.conn, dataset_id, eff_cfg)
                    did = dataset_id
                else:
                    # Single-symbol synthetic configs use the raw seed directly --
                    # byte-identical to pre-plan-04 behavior. named_child_seed only
                    # kicks in with more than one enabled symbol (see
                    # bot.engine.portfolio.build_portfolio_from_synthetic).
                    if entry.dataset_seed is not None:
                        derived_seed = entry.dataset_seed
                    elif len(enabled) == 1:
                        derived_seed = seed
                    else:
                        derived_seed = named_child_seed(seed, entry.symbol)
                    start_price = self.instruments_yaml.get(entry.symbol, {}).get(
                        "synthetic_start_price", 1.1000
                    )
                    did = self.create_dataset(
                        derived_seed,
                        bars,
                        entry.symbol,
                        eff_cfg.trading_day_rollover_tz,
                        eff_cfg.trading_day_rollover_time,
                        start_price=start_price,
                    )
                    bundle = load_bundle_for_dataset(self.conn, did, eff_cfg)

                symbol_datasets[entry.symbol] = did
                price_feed = Feed(frames=bundle.price)
                if dxy_frames is None and eff_cfg.symbol_type == "FOREX" and bundle.dxy is not None:
                    dxy_frames = bundle.dxy
                symbol_contexts[entry.symbol] = build_symbol_context(
                    eff_cfg, price_feed, instrument
                )

            dxy_feed = Feed(frames=dxy_frames) if dxy_frames is not None else None

            run_db_id = repo.create_run(
                self.conn, int(cfg_row["id"]), symbol_datasets, cfg.starting_equity
            )

            clock = Clock(min(sc.cursor for sc in symbol_contexts.values()))
            runner = Runner(self.conn, run_db_id, symbol_contexts, dxy_feed, cfg, clock)

            self.run_id = run_db_id
            self.runner = runner
            self.symbol_datasets_active = symbol_datasets
            self.config_version_id = int(cfg_row["id"])

            return self._run_info(run_db_id)

    def _run_info(self, run_db_id: int) -> dict[str, Any]:
        cur = self.conn.execute("SELECT * FROM run WHERE id=?", (run_db_id,))
        row = cur.fetchone()
        assert row is not None
        symbols_json = row["symbols_json"] if "symbols_json" in row.keys() else None
        return {
            "id": row["id"],
            "dataset_id": row["dataset_id"],
            "config_version_id": row["config_version_id"],
            "symbol": row["symbol"],
            "symbols": json.loads(symbols_json) if symbols_json else row["symbol"].split(","),
            "status": row["status"],
            "starting_equity": row["starting_equity"],
            "created_at_utc": row["created_at_utc"],
            "is_playing": self.is_playing(),
        }

    @_locked
    def get_run(self) -> dict[str, Any] | None:
        if self.run_id is None:
            return None
        return self._run_info(self.run_id)

    def step(self) -> list[StepSummary]:
        with self.lock:
            if self.runner is None:
                raise RuntimeError("no active run — POST /api/run first")
            return self.runner.step()

    def play(self, interval_ms: int = 200) -> None:
        with self.lock:
            if self.runner is None:
                raise RuntimeError("no active run — POST /api/run first")
            if self._play_thread is not None and self._play_thread.is_alive():
                return
            self._stop_event.clear()
            t = threading.Thread(target=self._play_loop, args=(interval_ms,), daemon=True)
            self._play_thread = t
            t.start()

    def _play_loop(self, interval_ms: int) -> None:
        while not self._stop_event.is_set():
            with self.lock:
                if self.runner is None:
                    break
                summaries = self.runner.step()
            if not summaries:
                break
            time.sleep(max(interval_ms, 1) / 1000.0)

    def pause(self) -> None:
        with self.lock:
            self._stop_play_locked()

    def _stop_play_locked(self) -> None:
        self._stop_event.set()
        t = self._play_thread
        self._play_thread = None
        if t is not None and t.is_alive() and t is not threading.current_thread():
            t.join(timeout=2.0)

    def is_playing(self) -> bool:
        t = self._play_thread
        return t is not None and t.is_alive()

    def reset(self) -> None:
        with self.lock:
            self._stop_play_locked()
            self.runner = None
            self.run_id = None
            self.symbol_datasets_active = None
            self.config_version_id = None

    # ----------------------------------------------------------------- account
    def _starting_equity_for_run(self, run_id: int) -> float:
        cur = self.conn.execute("SELECT starting_equity FROM run WHERE id=?", (run_id,))
        row = cur.fetchone()
        return float(row["starting_equity"]) if row is not None else 0.0

    def _peak_equity(self, run_id: int, starting: float) -> float:
        cur = self.conn.execute("SELECT MAX(equity) FROM equity_point WHERE run_id=?", (run_id,))
        row = cur.fetchone()
        peak = row[0] if row is not None and row[0] is not None else starting
        return max(float(peak), starting)

    @_locked
    def account_snapshot(self) -> dict[str, Any]:
        _, cfg = self.get_active_config()
        if self.run_id is None:
            return {
                "run_id": None,
                "equity": cfg.starting_equity,
                "balance": cfg.starting_equity,
                "drawdown_pct": 0.0,
                "open_trades": 0,
                "current_risk_pct": cfg.risk.max_risk_per_trade_pct,
                "daily_loss_count": 0,
                "daily_losses_remaining": cfg.filters.account_risk.daily_max_losses,
                "current_trading_day": None,
                "consecutive_wins": 0,
                "consecutive_losses": 0,
                "risk_multiplier": 1.0,
                "bot_enabled": True,
                "blocked_reason": None,
                "open_trades_by_symbol": {},
                "open_risk_pct_total": 0.0,
                "max_total_open_risk_pct": cfg.risk.max_total_open_risk_pct,
            }
        state = repo.get_account_state(self.conn, self.run_id)
        if state is None:
            raise RuntimeError("account_state missing for active run")
        equity = float(state["equity"])
        starting = self._starting_equity_for_run(self.run_id)
        peak = self._peak_equity(self.run_id, starting)
        drawdown_pct = 0.0 if peak <= 0 else max(0.0, (peak - equity) / peak * 100.0)
        account_risk_cfg = cfg.filters.account_risk
        daily_loss_count = int(state["daily_loss_count"])
        if account_risk_cfg.daily_loss_limit_enabled:
            remaining = max(0, account_risk_cfg.daily_max_losses - daily_loss_count)
        else:
            remaining = -1  # D10: unlimited (Stock VN)
        open_trades_by_symbol = {
            str(r[0]): int(r[1])
            for r in self.conn.execute(
                "SELECT symbol, COUNT(*) FROM trade WHERE run_id=? AND status IN "
                "('PENDING','OPEN') GROUP BY symbol",
                (self.run_id,),
            )
        }
        open_risk_pct_total = (
            sum(sc.trade.risk_pct_effective for sc in self.runner.symbols.values() if sc.trade)
            if self.runner is not None
            else 0.0
        )
        return {
            "run_id": self.run_id,
            "equity": equity,
            "balance": float(state["balance"]),
            "drawdown_pct": drawdown_pct,
            "open_trades": int(state["open_trades"]),
            "open_trades_by_symbol": open_trades_by_symbol,
            "current_risk_pct": cfg.risk.max_risk_per_trade_pct * float(state["risk_multiplier"]),
            "daily_loss_count": daily_loss_count,
            "daily_losses_remaining": remaining,
            "current_trading_day": state["current_trading_day"],
            "consecutive_wins": int(state["consecutive_wins"]),
            "consecutive_losses": int(state["consecutive_losses"]),
            "risk_multiplier": float(state["risk_multiplier"]),
            "bot_enabled": bool(state["bot_enabled"]),
            "blocked_reason": state["blocked_reason"],
            "open_risk_pct_total": open_risk_pct_total,
            "max_total_open_risk_pct": cfg.risk.max_total_open_risk_pct,
        }

    # ------------------------------------------------------------------ trades
    @_locked
    def list_trades(
        self,
        status: str | None = None,
        run_id: int | None = None,
        symbol: str | None = None,
    ) -> list[sqlite3.Row]:
        rid = run_id if run_id is not None else self.run_id
        if rid is None:
            return []
        query = "SELECT * FROM trade WHERE run_id=?"
        params: list[Any] = [rid]
        if status:
            query += " AND status=?"
            params.append(status)
        if symbol:
            query += " AND symbol=?"
            params.append(symbol)
        query += " ORDER BY id DESC"
        cur = self.conn.execute(query, params)
        return list(cur.fetchall())

    @_locked
    def get_trade(self, trade_id: int) -> sqlite3.Row | None:
        cur = self.conn.execute("SELECT * FROM trade WHERE id=?", (trade_id,))
        row: sqlite3.Row | None = cur.fetchone()
        return row

    @_locked
    def list_trade_events(self, trade_id: int) -> list[sqlite3.Row]:
        cur = self.conn.execute(
            "SELECT * FROM trade_event WHERE trade_id=? ORDER BY id ASC", (trade_id,)
        )
        return list(cur.fetchall())

    # ---------------------------------------------------------------- decisions
    @_locked
    def list_decisions(
        self,
        limit: int = 50,
        reason: str | None = None,
        outcome: str | None = None,
        run_id: int | None = None,
        symbol: str | None = None,
    ) -> list[sqlite3.Row]:
        rid = run_id if run_id is not None else self.run_id
        if rid is None:
            return []
        query = "SELECT * FROM decision WHERE run_id=?"
        params: list[Any] = [rid]
        if reason:
            query += " AND reason=?"
            params.append(reason)
        if outcome == "done":
            query += " AND reason='done'"
        elif outcome == "no_trade":
            query += " AND reason!='done'"
        if symbol:
            query += " AND symbol=?"
            params.append(symbol)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        cur = self.conn.execute(query, params)
        return list(cur.fetchall())

    @_locked
    def get_decision(self, decision_id: int) -> sqlite3.Row | None:
        cur = self.conn.execute("SELECT * FROM decision WHERE id=?", (decision_id,))
        row: sqlite3.Row | None = cur.fetchone()
        return row

    @_locked
    def list_decision_filters(self, decision_id: int) -> list[sqlite3.Row]:
        cur = self.conn.execute(
            "SELECT * FROM decision_filter WHERE decision_id=? ORDER BY id ASC", (decision_id,)
        )
        return list(cur.fetchall())

    @_locked
    def decision_stats(self, run_id: int | None = None) -> dict[str, int]:
        rid = run_id if run_id is not None else self.run_id
        if rid is None:
            return {}
        cur = self.conn.execute(
            "SELECT reason, COUNT(*) FROM decision WHERE run_id=? GROUP BY reason", (rid,)
        )
        return {row[0]: row[1] for row in cur.fetchall()}

    # ------------------------------------------------------------------ equity
    @_locked
    def list_equity_points(self, limit: int = 500, run_id: int | None = None) -> list[sqlite3.Row]:
        rid = run_id if run_id is not None else self.run_id
        if rid is None:
            return []
        cur = self.conn.execute(
            "SELECT * FROM equity_point WHERE run_id=? ORDER BY id DESC LIMIT ?",
            (rid, limit),
        )
        return list(reversed(cur.fetchall()))

    # ---------------------------------------------------------- run registry (plan 03)
    @_locked
    def get_run_row(self, run_id: int) -> sqlite3.Row | None:
        cur = self.conn.execute("SELECT * FROM run WHERE id=?", (run_id,))
        row: sqlite3.Row | None = cur.fetchone()
        return row

    @_locked
    def list_runs(self) -> list[dict[str, Any]]:
        cur = self.conn.execute(
            "SELECT r.*, cv.version AS config_version, "
            "(SELECT COUNT(*) FROM equity_point ep WHERE ep.run_id = r.id) AS bars_processed, "
            "(SELECT ep.equity FROM equity_point ep WHERE ep.run_id = r.id "
            " ORDER BY ep.id DESC LIMIT 1) AS final_equity, "
            "(SELECT COUNT(*) FROM trade t WHERE t.run_id = r.id AND t.status='CLOSED') "
            " AS closed_trades "
            "FROM run r JOIN config_version cv ON cv.id = r.config_version_id "
            "ORDER BY r.id DESC"
        )
        return [
            {
                "id": row["id"],
                "dataset_id": row["dataset_id"],
                "config_version_id": row["config_version_id"],
                "config_version": row["config_version"],
                "symbol": row["symbol"],
                "status": row["status"],
                "starting_equity": row["starting_equity"],
                "created_at_utc": row["created_at_utc"],
                "bars_processed": row["bars_processed"],
                "final_equity": row["final_equity"],
                "closed_trades": row["closed_trades"],
                "is_active": row["id"] == self.run_id,
            }
            for row in cur.fetchall()
        ]

    def _config_version_row(self, config_version_id: int) -> sqlite3.Row:
        """The config_version row behind an id. Raises KeyError if it is gone."""
        cur = self.conn.execute("SELECT * FROM config_version WHERE id=?", (config_version_id,))
        row: sqlite3.Row | None = cur.fetchone()
        if row is None:
            raise KeyError(config_version_id)
        return row

    def _run_config(self, run: sqlite3.Row) -> BotConfig:
        row = self._config_version_row(int(run["config_version_id"]))
        return BotConfig.model_validate_json(row["config_json"])

    @_locked
    def run_report(self, run_id: int) -> RunReport:
        run = self.get_run_row(run_id)
        if run is None:
            raise KeyError(run_id)
        closed = [
            dict(r)
            for r in self.conn.execute(
                "SELECT * FROM trade WHERE run_id=? AND status='CLOSED' ORDER BY id", (run_id,)
            )
        ]
        equity = [
            float(r[0])
            for r in self.conn.execute(
                "SELECT equity FROM equity_point WHERE run_id=? ORDER BY id", (run_id,)
            )
        ]
        blocks = {
            str(r[0]): int(r[1])
            for r in self.conn.execute(
                "SELECT df.filter_id, COUNT(*) FROM decision_filter df "
                "JOIN decision d ON d.id = df.decision_id "
                "WHERE d.run_id=? AND df.blocking=1 GROUP BY df.filter_id",
                (run_id,),
            )
        }
        return compute_run_report(
            closed,
            equity,
            float(run["starting_equity"]),
            self._run_config(run).timeframe,
            self.decision_stats(run_id=run_id),
            blocks,
        )

    @_locked
    def compare_runs(self, run_id_a: int, run_id_b: int) -> dict[str, Any]:
        run_a, run_b = self.get_run_row(run_id_a), self.get_run_row(run_id_b)
        if run_a is None:
            raise KeyError(run_id_a)
        if run_b is None:
            raise KeyError(run_id_b)
        report_a, report_b = self.run_report(run_id_a), self.run_report(run_id_b)
        # The user-facing "vN" is config_version.version, NOT the config_version row id —
        # list_runs exposes the same number as `config_version`.
        version_a = int(self._config_version_row(int(run_a["config_version_id"]))["version"])
        version_b = int(self._config_version_row(int(run_b["config_version_id"]))["version"])
        return {
            "run_a": run_id_a,
            "run_b": run_id_b,
            "dataset_a": run_a["dataset_id"],
            "dataset_b": run_b["dataset_id"],
            "config_version_a": version_a,
            "config_version_b": version_b,
            "same_dataset": run_a["dataset_id"] == run_b["dataset_id"],
            "same_config_version": run_a["config_version_id"] == run_b["config_version_id"],
            "metrics": diff_reports(report_a, report_b),
            "reason_histogram": diff_histograms(
                report_a.reason_histogram, report_b.reason_histogram
            ),
        }

    @_locked
    def delete_run(self, run_id: int) -> None:
        """Raises KeyError if unknown, ValueError if the run is the active one."""
        if self.get_run_row(run_id) is None:
            raise KeyError(run_id)
        if run_id == self.run_id:
            raise ValueError("cannot delete the active run — reset it first")
        # All-or-nothing: a half-deleted run (rows in `run` but no decisions) would be
        # silently committed by the next unrelated commit() on this shared connection.
        try:
            # trade <-> decision reference each other; break the cycle before deleting.
            self.conn.execute("UPDATE trade SET decision_id=NULL WHERE run_id=?", (run_id,))
            self.conn.execute("UPDATE decision SET trade_id=NULL WHERE run_id=?", (run_id,))
            self.conn.execute(
                "DELETE FROM decision_filter WHERE decision_id IN "
                "(SELECT id FROM decision WHERE run_id=?)",
                (run_id,),
            )
            self.conn.execute(
                "DELETE FROM trade_event WHERE trade_id IN (SELECT id FROM trade WHERE run_id=?)",
                (run_id,),
            )
            self.conn.execute("DELETE FROM decision WHERE run_id=?", (run_id,))
            self.conn.execute("DELETE FROM trade WHERE run_id=?", (run_id,))
            self.conn.execute("DELETE FROM equity_point WHERE run_id=?", (run_id,))
            self.conn.execute("DELETE FROM account_state WHERE run_id=?", (run_id,))
            self.conn.execute("DELETE FROM breakout_state WHERE run_id=?", (run_id,))
            self.conn.execute("DELETE FROM run_symbol_dataset WHERE run_id=?", (run_id,))
            self.conn.execute("DELETE FROM run WHERE id=?", (run_id,))
        except Exception:
            self.conn.rollback()
            raise
        self.conn.commit()

    @_locked
    def run_bars(
        self,
        run_id: int,
        tf: str,
        from_ts: str | None = None,
        to_ts: str | None = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        """OHLC bars of the run's dataset, only bars CLOSED at the run's current clock
        (open_ts + tf_duration <= last processed bar close — no future bars, C11).

        Returns at most `limit` bars, the most recent ones: this is polled once a second
        by the dashboard chart and a dataset can hold tens of thousands of bars."""
        run = self.get_run_row(run_id)
        if run is None:
            raise KeyError(run_id)
        if tf not in TF_DURATION:
            raise ConfigError(f"unknown timeframe {tf!r}")
        cur = self.conn.execute(
            "SELECT bar_ts_utc FROM equity_point WHERE run_id=? ORDER BY id DESC LIMIT 1",
            (run_id,),
        )
        last = cur.fetchone()
        if last is None:
            return []  # no bar processed yet -> nothing is closed for this run

        frames = self._price_frames(run["dataset_id"], int(run["config_version_id"]))
        df = frames.get(tf)
        if df is None:
            # Not the same thing as "nothing closed yet" — say so instead of a blank chart.
            raise ConfigError(
                f"timeframe {tf!r} is not available for this dataset "
                f"(available: {', '.join(sorted(frames))})"
            )

        def _aligned(ts_str: str) -> pd.Timestamp:
            """Timestamps arrive with or without an offset (query strings often lose
            the `+`); align tz-awareness with the frame index so comparisons work."""
            t = pd.Timestamp(ts_str)
            index_tz = getattr(df.index, "tz", None)
            if index_tz is not None:
                return t.tz_localize(index_tz) if t.tz is None else t.tz_convert(index_tz)
            return t.tz_convert("UTC").tz_localize(None) if t.tz is not None else t

        visible = df[df.index + TF_DURATION[tf] <= _aligned(last["bar_ts_utc"])]
        if from_ts:
            visible = visible[visible.index >= _aligned(from_ts)]
        if to_ts:
            visible = visible[visible.index <= _aligned(to_ts)]
        if limit > 0 and len(visible) > limit:
            visible = visible.iloc[-limit:]
        # Column-wise .tolist() instead of iterrows(): the latter boxes a Series per bar.
        return [
            {"ts_utc": ts.isoformat(), "open": o, "high": h, "low": lo, "close": c}
            for ts, o, h, lo, c in zip(
                visible.index,
                visible["open"].astype(float).tolist(),
                visible["high"].astype(float).tolist(),
                visible["low"].astype(float).tolist(),
                visible["close"].astype(float).tolist(),
                strict=True,
            )
        ]

    def _price_frames(self, dataset_id: str, config_version_id: int) -> dict[str, pd.DataFrame]:
        """Small per-(dataset, config-version) LRU cache: bundle loading regenerates/reads
        the whole dataset, far too slow to do per chart poll. Invalidated by
        `_invalidate_bars_cache` whenever a dataset's underlying bars can have changed."""
        key = (dataset_id, config_version_id)
        cached = self._bars_cache.get(key)
        if cached is not None:
            self._bars_cache.move_to_end(key)  # LRU: don't evict the frame in active use
            return cached
        cfg = BotConfig.model_validate_json(
            self._config_version_row(config_version_id)["config_json"]
        )
        bundle = load_bundle_for_dataset(self.conn, dataset_id, cfg)
        while len(self._bars_cache) >= _BARS_CACHE_MAX:
            self._bars_cache.popitem(last=False)
        self._bars_cache[key] = bundle.price
        return bundle.price

    def _invalidate_bars_cache(self, dataset_id: str | None = None) -> None:
        """Drop cached frames for one dataset (or all). Must be called whenever the bars
        behind a dataset id can have changed, or the chart serves pre-import prices."""
        if dataset_id is None:
            self._bars_cache.clear()
            return
        for key in [k for k in self._bars_cache if k[0] == dataset_id]:
            del self._bars_cache[key]

    # ----------------------------------------------------------------- symbols
    def list_symbols(self) -> list[dict[str, str]]:
        return [
            {"symbol": k, "symbol_type": v.get("symbol_type", "")}
            for k, v in self.instruments_yaml.items()
        ]

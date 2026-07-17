"""RunnerService: thread-safe orchestration of engine/runner.py for the API.

No business logic lives here — it wires config/dataset/feed/Runner together (the same
way cli.py does for `replay`) and exposes step/play/pause/reset behind a lock. Plan:
step-synchronous by default; "play" is a background worker thread holding the lock so
step/play/pause/reset never race.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from bot.config.loader import deep_merge, load_default_config, load_instruments
from bot.config.metadata import metadata_by_field
from bot.config.models import BotConfig
from bot.core.clock import Clock
from bot.core.errors import ConfigError
from bot.core.types import InstrumentSpec
from bot.data.dataset import DatasetSpec, generate_bundle
from bot.data.dataset import dataset_id as compute_dataset_id
from bot.data.feed import Feed
from bot.db import repositories as repo
from bot.db.connection import migrate
from bot.engine.runner import Runner, StepSummary
from bot.filters.registry import ALL_FILTER_IDS


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
        self.dataset_id_active: str | None = None
        self.config_version_id: int | None = None

        self._play_thread: threading.Thread | None = None
        self._stop_event = threading.Event()

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

    def get_active_config(self) -> tuple[sqlite3.Row, BotConfig]:
        row = repo.get_active_config_version(self.conn)
        if row is None:
            raise ConfigError("no active config version")
        cfg = BotConfig.model_validate_json(row["config_json"])
        return row, cfg

    def patch_config(self, patch: dict[str, Any], note: str = "") -> sqlite3.Row:
        row, _cfg = self.get_active_config()
        base = json.loads(row["config_json"])
        merged = deep_merge(base, patch)
        new_cfg = BotConfig.model_validate(merged)  # raises pydantic.ValidationError on bad input
        repo.create_config_version(self.conn, new_cfg.model_dump_json(), note=note)
        row2 = repo.get_active_config_version(self.conn)
        assert row2 is not None
        return row2

    def list_config_versions(self) -> list[sqlite3.Row]:
        cur = self.conn.execute("SELECT * FROM config_version ORDER BY version DESC")
        return list(cur.fetchall())

    def activate_config_version(self, config_version_id: int) -> sqlite3.Row:
        cur = self.conn.execute("SELECT id FROM config_version WHERE id=?", (config_version_id,))
        if cur.fetchone() is None:
            raise KeyError(config_version_id)
        repo.activate_config_version(self.conn, config_version_id)
        row = repo.get_active_config_version(self.conn)
        assert row is not None
        return row

    # --------------------------------------------------------------- filters
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
    def create_dataset(
        self, seed: int, bars: int, symbol: str, rollover_tz: str, rollover_time: str
    ) -> str:
        n_candles_15m = (bars + 400) * 4
        spec = DatasetSpec(
            seed=seed,
            n_candles_15m=n_candles_15m,
            symbol=symbol,
            rollover_tz=rollover_tz,
            rollover_time=rollover_time,
        )
        did = compute_dataset_id(spec)
        repo.upsert_dataset(self.conn, did, json.dumps(asdict(spec)))
        return did

    def list_datasets(self) -> list[dict[str, Any]]:
        cur = self.conn.execute("SELECT * FROM dataset ORDER BY created_at_utc DESC")
        out: list[dict[str, Any]] = []
        for row in cur.fetchall():
            spec = json.loads(row["spec_json"])
            out.append(
                {
                    "id": row["id"],
                    "seed": spec["seed"],
                    "n_candles_15m": spec["n_candles_15m"],
                    "created_at_utc": row["created_at_utc"],
                }
            )
        return out

    def _load_dataset_spec(self, dataset_id: str) -> DatasetSpec:
        cur = self.conn.execute("SELECT spec_json FROM dataset WHERE id=?", (dataset_id,))
        row = cur.fetchone()
        if row is None:
            raise KeyError(dataset_id)
        return DatasetSpec(**json.loads(row["spec_json"]))

    # ------------------------------------------------------------- run/step
    def _build_instrument(self, cfg: BotConfig) -> InstrumentSpec:
        spec = self.instruments_yaml.get(cfg.symbol)
        if spec is None:
            raise ConfigError(f"no instrument spec for symbol {cfg.symbol!r}")
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
            instrument = self._build_instrument(cfg)

            if dataset_id is None:
                dataset_id = self.create_dataset(
                    seed, bars, cfg.symbol, cfg.trading_day_rollover_tz,
                    cfg.trading_day_rollover_time,
                )
            spec = self._load_dataset_spec(dataset_id)

            bundle = generate_bundle(spec)
            price_feed = Feed(frames=bundle["price"])
            dxy_feed = Feed(frames=bundle["dxy"])

            run_db_id = repo.create_run(
                self.conn, dataset_id, int(cfg_row["id"]), cfg.symbol, cfg.starting_equity
            )

            primary = cfg.timeframe
            first_ts = price_feed.frames[primary].index[0].to_pydatetime()
            clock = Clock(first_ts)
            runner = Runner(self.conn, run_db_id, price_feed, dxy_feed, cfg, instrument, clock)

            self.run_id = run_db_id
            self.runner = runner
            self.dataset_id_active = dataset_id
            self.config_version_id = int(cfg_row["id"])

            return self._run_info(run_db_id)

    def _run_info(self, run_db_id: int) -> dict[str, Any]:
        cur = self.conn.execute("SELECT * FROM run WHERE id=?", (run_db_id,))
        row = cur.fetchone()
        assert row is not None
        return {
            "id": row["id"],
            "dataset_id": row["dataset_id"],
            "config_version_id": row["config_version_id"],
            "symbol": row["symbol"],
            "status": row["status"],
            "starting_equity": row["starting_equity"],
            "created_at_utc": row["created_at_utc"],
            "is_playing": self.is_playing(),
        }

    def get_run(self) -> dict[str, Any] | None:
        if self.run_id is None:
            return None
        return self._run_info(self.run_id)

    def step(self) -> StepSummary | None:
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
                summary = self.runner.step()
            if summary is None:
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
            self.dataset_id_active = None
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
        return {
            "run_id": self.run_id,
            "equity": equity,
            "balance": float(state["balance"]),
            "drawdown_pct": drawdown_pct,
            "open_trades": int(state["open_trades"]),
            "current_risk_pct": cfg.risk.max_risk_per_trade_pct * float(state["risk_multiplier"]),
            "daily_loss_count": daily_loss_count,
            "daily_losses_remaining": remaining,
            "current_trading_day": state["current_trading_day"],
            "consecutive_wins": int(state["consecutive_wins"]),
            "consecutive_losses": int(state["consecutive_losses"]),
            "risk_multiplier": float(state["risk_multiplier"]),
            "bot_enabled": bool(state["bot_enabled"]),
            "blocked_reason": state["blocked_reason"],
        }

    # ------------------------------------------------------------------ trades
    def list_trades(self, status: str | None = None) -> list[sqlite3.Row]:
        if self.run_id is None:
            return []
        if status:
            cur = self.conn.execute(
                "SELECT * FROM trade WHERE run_id=? AND status=? ORDER BY id DESC",
                (self.run_id, status),
            )
        else:
            cur = self.conn.execute(
                "SELECT * FROM trade WHERE run_id=? ORDER BY id DESC", (self.run_id,)
            )
        return list(cur.fetchall())

    def get_trade(self, trade_id: int) -> sqlite3.Row | None:
        cur = self.conn.execute("SELECT * FROM trade WHERE id=?", (trade_id,))
        row: sqlite3.Row | None = cur.fetchone()
        return row

    def list_trade_events(self, trade_id: int) -> list[sqlite3.Row]:
        cur = self.conn.execute(
            "SELECT * FROM trade_event WHERE trade_id=? ORDER BY id ASC", (trade_id,)
        )
        return list(cur.fetchall())

    # ---------------------------------------------------------------- decisions
    def list_decisions(
        self, limit: int = 50, reason: str | None = None, outcome: str | None = None
    ) -> list[sqlite3.Row]:
        if self.run_id is None:
            return []
        query = "SELECT * FROM decision WHERE run_id=?"
        params: list[Any] = [self.run_id]
        if reason:
            query += " AND reason=?"
            params.append(reason)
        if outcome == "done":
            query += " AND reason='done'"
        elif outcome == "no_trade":
            query += " AND reason!='done'"
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        cur = self.conn.execute(query, params)
        return list(cur.fetchall())

    def get_decision(self, decision_id: int) -> sqlite3.Row | None:
        cur = self.conn.execute("SELECT * FROM decision WHERE id=?", (decision_id,))
        row: sqlite3.Row | None = cur.fetchone()
        return row

    def list_decision_filters(self, decision_id: int) -> list[sqlite3.Row]:
        cur = self.conn.execute(
            "SELECT * FROM decision_filter WHERE decision_id=? ORDER BY id ASC", (decision_id,)
        )
        return list(cur.fetchall())

    def decision_stats(self) -> dict[str, int]:
        if self.run_id is None:
            return {}
        cur = self.conn.execute(
            "SELECT reason, COUNT(*) FROM decision WHERE run_id=? GROUP BY reason", (self.run_id,)
        )
        return {row[0]: row[1] for row in cur.fetchall()}

    # ------------------------------------------------------------------ equity
    def list_equity_points(self, limit: int = 500) -> list[sqlite3.Row]:
        if self.run_id is None:
            return []
        cur = self.conn.execute(
            "SELECT * FROM equity_point WHERE run_id=? ORDER BY id DESC LIMIT ?",
            (self.run_id, limit),
        )
        return list(reversed(cur.fetchall()))

    # ----------------------------------------------------------------- symbols
    def list_symbols(self) -> list[dict[str, str]]:
        return [
            {"symbol": k, "symbol_type": v.get("symbol_type", "")}
            for k, v in self.instruments_yaml.items()
        ]

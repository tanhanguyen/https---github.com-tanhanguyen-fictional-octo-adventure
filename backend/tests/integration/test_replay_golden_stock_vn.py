"""Plan 05 golden runs: a full backtest per new SYMBOL_TYPE over a fixed D1 CSV.

Fixtures (`tests/fixtures/csv/{hpg,vn30f1m}_1d_sample.csv`) are 600 weekday daily bars
stamped 02:00 UTC (= 09:00 Asia/Ho_Chi_Minh, the real session open, matching the format
`scripts/convert_csv.py vnstock` produces). 600 bars ~ 2.4 years, deliberately long
enough for EMA89 on the 1W confirmation frame to leave warmup (plan 05: a shorter file
would sit in `wait/warmup` forever, by design but silently).

Beyond determinism these assert the market rules END-TO-END, on real decision/trade
rows rather than on a unit-test's hand-built bar: cash never shorts, cash never exits
before T+2, and no VN30F position outlives its expiry.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime
from pathlib import Path

from bot.config.loader import load_default_config, load_instruments
from bot.config.models import BotConfig, effective_config_for_symbol
from bot.core.clock import Clock
from bot.core.timeframes import trading_day, vn30f_expiry
from bot.core.types import InstrumentSpec
from bot.data.csv_feed import load_csv
from bot.data.feed import Feed
from bot.db import repositories as repo
from bot.db.connection import connect_and_migrate
from bot.engine.context import build_symbol_context
from bot.engine.runner import Runner

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "csv"
HPG_CSV = FIXTURES / "hpg_1d_sample.csv"
VN30F_CSV = FIXTURES / "vn30f1m_1d_sample.csv"

# 500 million VND -- an all-VN portfolio is a VND account (user decision 2026-07-22),
# so `starting_equity` is read as VND and never mixed with a USD symbol.
STARTING_EQUITY_VND = 500_000_000.0


def _instrument(symbol: str) -> InstrumentSpec:
    spec = load_instruments()[symbol]
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


def _run_vn(symbol: str, symbol_type: str, csv_path: Path, tag: str):
    base = load_default_config()
    config = BotConfig.model_validate(
        {
            **base.model_dump(mode="json"),
            "starting_equity": STARTING_EQUITY_VND,
            "symbols": [{"symbol": symbol, "symbol_type": symbol_type}],
        }
    )
    eff_cfg = effective_config_for_symbol(config, config.symbols[0])
    assert eff_cfg.timeframe == "1D"

    frames = load_csv(
        csv_path, "1D", eff_cfg.trading_day_rollover_tz, eff_cfg.trading_day_rollover_time
    )
    symbols = {
        symbol: build_symbol_context(eff_cfg, Feed(frames=frames), _instrument(symbol))
    }

    conn = connect_and_migrate(":memory:")
    repo.upsert_dataset(conn, f"{tag}:{symbol}", "{}")
    cv_id = repo.create_config_version(conn, config.model_dump_json())
    run_id = repo.create_run(conn, cv_id, {symbol: f"{tag}:{symbol}"}, config.starting_equity)

    clock = Clock(min(sc.cursor for sc in symbols.values()))
    runner = Runner(conn, run_id, symbols, None, config, clock)

    stream = []
    while True:
        summaries = runner.step()
        if not summaries:
            break
        for s in summaries:
            stream.append((s.bar_ts, s.symbol, s.reason, s.stage))
    return conn, run_id, stream, runner.equity


def _trades(conn: sqlite3.Connection, run_id: int) -> list[sqlite3.Row]:
    return list(conn.execute("SELECT * FROM trade WHERE run_id=? ORDER BY id", (run_id,)))


def _events(conn: sqlite3.Connection, run_id: int) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT te.* FROM trade_event te JOIN trade t ON t.id = te.trade_id "
            "WHERE t.run_id=? ORDER BY te.id",
            (run_id,),
        )
    )


def _vn_day(iso_ts: str) -> date:
    return trading_day(datetime.fromisoformat(iso_ts), "Asia/Ho_Chi_Minh", "00:00")


# ---------------------------------------------------------------------------
# Determinism (invariant #1)
# ---------------------------------------------------------------------------


def test_stock_vn_cash_replay_is_deterministic():
    conn1, _, stream1, equity1 = _run_vn("HPG", "STOCK_VN_CASH", HPG_CSV, "vn-cash-a")
    conn2, _, stream2, equity2 = _run_vn("HPG", "STOCK_VN_CASH", HPG_CSV, "vn-cash-b")
    assert stream1 == stream2
    assert equity1 == equity2
    conn1.close()
    conn2.close()


def test_stock_vn_deriv_replay_is_deterministic():
    conn1, _, stream1, equity1 = _run_vn("VN30F1M", "STOCK_VN_DERIV", VN30F_CSV, "vn-fut-a")
    conn2, _, stream2, equity2 = _run_vn("VN30F1M", "STOCK_VN_DERIV", VN30F_CSV, "vn-fut-b")
    assert stream1 == stream2
    assert equity1 == equity2
    conn1.close()
    conn2.close()


# ---------------------------------------------------------------------------
# The run actually covers the file and reaches real decisions
# ---------------------------------------------------------------------------


def test_backtest_runs_over_the_whole_cash_csv():
    conn, run_id, stream, equity = _run_vn("HPG", "STOCK_VN_CASH", HPG_CSV, "vn-cash-cov")
    try:
        assert len(stream) == 600  # every daily bar in the fixture was decided on
        reasons = {reason for _ts, _sym, reason, _stage in stream}
        # Warmup must END: a fixture too short for EMA89-on-1W would be all-warmup.
        stages = {stage for _ts, _sym, _r, stage in stream}
        assert "warmup" in stages  # the beginning of the file, as designed (C12)
        assert reasons - {"wait"}, "run never got past `wait`"
        assert equity > 0
    finally:
        conn.close()


def test_backtest_runs_over_the_whole_deriv_csv():
    conn, run_id, stream, equity = _run_vn("VN30F1M", "STOCK_VN_DERIV", VN30F_CSV, "vn-fut-cov")
    try:
        assert len(stream) == 600
        assert equity > 0
    finally:
        conn.close()


def test_session_gate_never_blocks_a_vn_daily_bar():
    """Regression: comparing a 1D bar's 00:00 ICT close against the intraday session
    windows would block 100% of bars -- the run would be a wall of `wait/session`."""
    conn, run_id, stream, _ = _run_vn("HPG", "STOCK_VN_CASH", HPG_CSV, "vn-cash-sess")
    try:
        assert not [s for _ts, _sym, _r, s in stream if s == "session"]
        blocked = conn.execute(
            "SELECT COUNT(*) FROM decision_filter df JOIN decision d ON d.id=df.decision_id "
            "WHERE d.run_id=? AND df.filter_id='session' AND df.blocking=1",
            (run_id,),
        ).fetchone()[0]
        assert blocked == 0
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Market rules, asserted on the real trade rows
# ---------------------------------------------------------------------------


def test_cash_run_never_opens_a_short():
    conn, run_id, stream, _ = _run_vn("HPG", "STOCK_VN_CASH", HPG_CSV, "vn-cash-short")
    try:
        directions = {row["direction"] for row in _trades(conn, run_id)}
        assert directions, "fixture produced no trades -- assertion would be vacuous"
        assert "SELL" not in directions
        # This fixture never completes a SELL retest (a breakout is only armed in a
        # BEAR trend regime), so the *block itself* is exercised directly in
        # tests/unit/test_stock_vn_decisions.py rather than asserted on here.
    finally:
        conn.close()


def test_cash_run_never_exits_before_t_plus_2():
    """T+2.5 end-to-end: every closed trade was held at least 2 VN trading days."""
    conn, run_id, _stream, _ = _run_vn("HPG", "STOCK_VN_CASH", HPG_CSV, "vn-cash-t25")
    try:
        closed = [
            r
            for r in _trades(conn, run_id)
            if r["status"] == "CLOSED" and r["opened_at_utc"] and r["closed_at_utc"]
        ]
        assert closed, "fixture produced no closed trades -- assertion would be vacuous"
        for row in closed:
            held_days = (_vn_day(row["closed_at_utc"]) - _vn_day(row["opened_at_utc"])).days
            assert held_days >= 2, f"trade {row['id']} exited after {held_days} day(s)"
    finally:
        conn.close()


def test_cash_run_records_suppressed_exits_rather_than_hiding_them():
    conn, run_id, _stream, _ = _run_vn("HPG", "STOCK_VN_CASH", HPG_CSV, "vn-cash-supp")
    try:
        suppressed = [
            e for e in _events(conn, run_id) if e["event_type"] == "exit_suppressed_settlement"
        ]
        assert suppressed, "no settlement suppression happened -- fixture is not exercising T+2.5"
        for ev in suppressed:
            assert "unsettled" in ev["detail"]
    finally:
        conn.close()


def test_no_vn30f_position_outlives_its_expiry():
    """A position that meets an expiry during its life must be force-closed there.

    Note the timestamp convention: a bar closed at `bar.close_ts`, and a VN daily bar
    is stamped by its 09:00 ICT session OPEN, so an expiry-day close is timestamped
    09:00 ICT of the FOLLOWING session -- the same convention the time stop already
    uses. The assertion is therefore phrased over expiry dates inside the holding
    window plus the engine's own `expiry_close` event, not over raw close dates."""
    conn, run_id, _stream, _ = _run_vn("VN30F1M", "STOCK_VN_DERIV", VN30F_CSV, "vn-fut-exp")
    try:
        expiry_closed_trade_ids = {
            e["trade_id"] for e in _events(conn, run_id) if e["event_type"] == "expiry_close"
        }
        assert expiry_closed_trade_ids, "fixture never exercised an expiry force-close"

        closed = [
            r
            for r in _trades(conn, run_id)
            if r["status"] == "CLOSED" and r["opened_at_utc"] and r["closed_at_utc"]
        ]
        assert closed
        for row in closed:
            opened, closed_on = _vn_day(row["opened_at_utc"]), _vn_day(row["closed_at_utc"])
            expiries = []
            day = opened
            while day < closed_on:
                if day == vn30f_expiry(day.year, day.month):
                    expiries.append(day)
                day = date.fromordinal(day.toordinal() + 1)
            # At most ONE expiry may fall in a holding window, and only if that expiry
            # is exactly what ended the trade.
            assert len(expiries) <= 1, f"trade {row['id']} spanned expiries {expiries}"
            if expiries:
                assert row["id"] in expiry_closed_trade_ids, (
                    f"trade {row['id']} lived through expiry {expiries[0]} without a "
                    "force-close"
                )
    finally:
        conn.close()


def test_expiry_force_close_lands_on_a_real_third_thursday():
    conn, run_id, _stream, _ = _run_vn("VN30F1M", "STOCK_VN_DERIV", VN30F_CSV, "vn-fut-exp2")
    try:
        events = [e for e in _events(conn, run_id) if e["event_type"] == "expiry_close"]
        assert events
        for ev in events:
            expiry = date.fromisoformat(ev["detail"].split()[-1])
            assert expiry == vn30f_expiry(expiry.year, expiry.month)
            assert expiry.weekday() == 3
            # Booked at the close of the expiry bar -> the next session (<= 4 days
            # later, allowing for the weekend).
            gap = (_vn_day(ev["ts_utc"]) - expiry).days
            assert 0 < gap <= 4
    finally:
        conn.close()


def test_vn_trades_are_whole_lots():
    for symbol, symbol_type, csv in (
        ("HPG", "STOCK_VN_CASH", HPG_CSV),
        ("VN30F1M", "STOCK_VN_DERIV", VN30F_CSV),
    ):
        conn, run_id, _stream, _ = _run_vn(symbol, symbol_type, csv, f"vn-lots-{symbol}")
        try:
            sized = [r["lot_size"] for r in _trades(conn, run_id) if r["lot_size"] is not None]
            assert sized
            for lot in sized:
                assert float(lot).is_integer() and lot >= 1
        finally:
            conn.close()

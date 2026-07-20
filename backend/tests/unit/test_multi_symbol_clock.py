"""Plan 04 DoD scenarios: merged clock across mixed timeframes, deterministic
alphabetical tie-break for the last MAX_CONCURRENT_TRADES slot, and daily-loss-limit
being portfolio-wide (not per-symbol)."""

from __future__ import annotations

from unittest.mock import patch

from bot.config.loader import load_default_config, load_instruments
from bot.config.models import SymbolEntry
from bot.core.clock import Clock
from bot.core.timeframes import trading_day
from bot.core.types import Direction, OrderStatus, StrategyName, TPRules
from bot.db import repositories as repo
from bot.db.connection import connect_and_migrate
from bot.engine.decision_log import DecisionBundle
from bot.engine.main_loop import MainLoopResult
from bot.engine.order_engine import OpenTrade
from bot.engine.portfolio import build_portfolio_from_synthetic
from bot.engine.runner import Runner


def _make_run(config, portfolio):
    conn = connect_and_migrate(":memory:")
    symbol_datasets = {sym: f"test:{sym}" for sym in portfolio.symbols}
    for did in symbol_datasets.values():
        repo.upsert_dataset(conn, did, "{}")
    cv_id = repo.create_config_version(conn, config.model_dump_json())
    run_id = repo.create_run(conn, cv_id, symbol_datasets, config.starting_equity)
    clock = Clock(min(sc.cursor for sc in portfolio.symbols.values()))
    runner = Runner(conn, run_id, portfolio.symbols, portfolio.dxy_feed, config, clock)
    return conn, run_id, runner


def test_mixed_timeframe_clock_merges_and_interleaves():
    """Not just same-TF-offset schedules: EURUSD stays on its default 15m while GBPUSD
    overrides to 1D -- the merged clock must still advance monotonically and process
    both, with the coarser timeframe accumulating far fewer ticks."""
    config = load_default_config()
    config.symbols = [
        SymbolEntry(symbol="EURUSD", symbol_type="FOREX"),
        SymbolEntry(symbol="GBPUSD", symbol_type="FOREX", overrides={"timeframe": "1D"}),
    ]
    portfolio = build_portfolio_from_synthetic(config, load_instruments(), 42, (300 + 400) * 4)
    conn, _run_id, runner = _make_run(config, portfolio)

    bar_ts_seen: list[str] = []
    per_symbol_ticks: dict[str, int] = {"EURUSD": 0, "GBPUSD": 0}
    for _ in range(300):
        summaries = runner.step()
        if not summaries:
            break
        for s in summaries:
            bar_ts_seen.append(s.bar_ts)
            per_symbol_ticks[s.symbol] += 1

    conn.close()

    assert per_symbol_ticks["EURUSD"] > 0
    assert per_symbol_ticks["GBPUSD"] > 0
    # 1D is 96x coarser than 15m -- GBPUSD must accumulate far fewer ticks.
    assert per_symbol_ticks["GBPUSD"] * 10 < per_symbol_ticks["EURUSD"]
    # The merged clock never goes backwards.
    assert bar_ts_seen == sorted(bar_ts_seen)


def _fake_signal_always_fires(ctx, breakout_state, config):
    """Forces a BREAKOUT signal on every call, but still runs the REAL account_risk gate
    (ctx.open_trades_count/symbol_open_trade) so the portfolio slot-contention logic
    under test is the genuine one, not reimplemented in the test."""
    from bot.core.types import DecisionOutcome
    from bot.filters import account_risk as account_risk_filter

    account_risk_result = account_risk_filter.evaluate(ctx)
    if account_risk_result.blocking:
        outcome = DecisionOutcome(
            reason=account_risk_result.values["reason"],
            stage=account_risk_result.values["stage"],
            detail=account_risk_result.detail,
        )
        bundle = DecisionBundle(
            outcome=outcome,
            filter_results={"account_risk": account_risk_result},
            signal=None,
            strategy=None,
        )
        return MainLoopResult(
            bundle=bundle, open_trade_candidate=None, breakout_state=breakout_state
        )

    outcome = DecisionOutcome(reason="done", stage="place_order", detail="forced for test")
    bundle = DecisionBundle(
        outcome=outcome,
        filter_results={"account_risk": account_risk_result},
        signal=None,
        strategy=StrategyName.BREAKOUT,
    )
    trade = OpenTrade(
        local_id=0,
        symbol=config.symbol,
        strategy=StrategyName.BREAKOUT,
        direction=Direction.BUY,
        status=OrderStatus.PENDING,
        sl=1.0,
        tp_rules=TPRules(kind="R_MULTIPLE", tp1_r=1.5, tp2_r=3.0),
        risk_pct_effective=1.0,
    )
    return MainLoopResult(bundle=bundle, open_trade_candidate=trade, breakout_state=breakout_state)


def test_alphabetical_order_decides_last_slot_when_tied():
    """DoD scenario (b): two symbols on the SAME timeframe both signal `done` at the
    same merged tick; MAX_CONCURRENT_TRADES=1 means only one can fill -- the
    alphabetically-first symbol must win the slot, the other must be blocked in the
    same tick with max_concurrent_trades_reached."""
    config = load_default_config()
    config.filters.account_risk.max_concurrent_trades = 1
    config.symbols = [
        SymbolEntry(symbol="AAAUSD", symbol_type="FOREX"),
        SymbolEntry(symbol="ZZZUSD", symbol_type="FOREX"),
    ]
    # AAAUSD/ZZZUSD aren't real instruments -- reuse EURUSD's spec via a patched
    # instruments_yaml so build_portfolio_from_synthetic can still build InstrumentSpecs.
    instruments = load_instruments()
    instruments["AAAUSD"] = {**instruments["EURUSD"], "symbol": "AAAUSD"}
    instruments["ZZZUSD"] = {**instruments["EURUSD"], "symbol": "ZZZUSD"}

    portfolio = build_portfolio_from_synthetic(config, instruments, 42, (50 + 400) * 4)
    conn, _run_id, runner = _make_run(config, portfolio)

    with patch("bot.engine.runner.main_loop.decide", side_effect=_fake_signal_always_fires):
        summaries = runner.step()

    conn.close()

    assert {s.symbol for s in summaries} == {"AAAUSD", "ZZZUSD"}
    by_symbol = {s.symbol: s for s in summaries}
    assert by_symbol["AAAUSD"].reason == "done"
    assert by_symbol["ZZZUSD"].reason == "max_concurrent_trades_reached"


def test_daily_loss_limit_is_portfolio_wide_not_per_symbol():
    """DoD scenario (c): EURUSD racks up 3 losses in a trading day -- GBPUSD's decision
    that same day must also come back daily_loss_limit_reached, since the counter is
    account-wide (bot.db.repositories.daily_loss_count is keyed by run_id only)."""
    config = load_default_config()
    config.symbols = [
        SymbolEntry(symbol="EURUSD", symbol_type="FOREX"),
        SymbolEntry(symbol="GBPUSD", symbol_type="FOREX"),
    ]
    portfolio = build_portfolio_from_synthetic(config, load_instruments(), 42, (50 + 400) * 4)
    conn, run_id, runner = _make_run(config, portfolio)

    current_day = trading_day(
        runner.clock.now, config.trading_day_rollover_tz, config.trading_day_rollover_time
    ).isoformat()
    for _ in range(3):
        trade_id = repo.insert_trade(
            conn,
            repo.TradeRecord(
                run_id=run_id,
                symbol="EURUSD",
                strategy="BREAKOUT",
                direction="BUY",
                status="CLOSED",
                result="LOSS",
                trading_day=current_day,
            ),
        )
        assert trade_id is not None

    summaries = runner.step()
    conn.close()

    assert summaries  # at least one symbol processed this tick
    for s in summaries:
        assert s.reason == "daily_loss_limit_reached"

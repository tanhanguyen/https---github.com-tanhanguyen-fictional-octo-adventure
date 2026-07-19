"""Decision resolution + persistence. Evaluate-all, decide-after (plan): every filter
gets a row every bar; the final (reason, stage, detail) triple is picked by walking
filter results in the §8 priority order. §8 reason vocabulary kept verbatim; stage/detail
add the UI-grade context §8 collapses away.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from bot.core.types import DecisionOutcome, FilterResult, Signal, StrategyName
from bot.db import repositories as repo
from bot.filters.registry import ALL_FILTER_IDS

WARMUP_REGIME_IDS = ("trend", "adx_filter", "er_filter", "atr_ref")


@dataclass
class DecisionBundle:
    outcome: DecisionOutcome
    filter_results: dict[str, FilterResult]
    signal: Signal | None
    strategy: StrategyName | None


def _is_warmup(fr: FilterResult) -> bool:
    return fr.enabled and not fr.evaluated and fr.passed is None


def resolve_decision(
    filter_results: dict[str, FilterResult],
    signal: Signal | None,
    strategy_candidate: StrategyName | None,
    regime_undecided: bool,
) -> DecisionOutcome:
    fr = filter_results

    account_risk = fr.get("account_risk")
    if account_risk is not None and account_risk.blocking:
        reason = account_risk.values.get("reason", "daily_loss_limit_reached")
        stage = account_risk.values.get("stage", "account_risk")
        return DecisionOutcome(reason=reason, stage=stage, detail=account_risk.detail)

    session = fr.get("session")
    if session is not None and session.blocking:
        return DecisionOutcome(reason="wait", stage="session", detail=session.detail)

    news = fr.get("news")
    if news is not None and news.blocking:
        return DecisionOutcome(reason="wait", stage="news", detail=news.detail)

    atr_zscore = fr.get("atr_zscore")
    if atr_zscore is not None and atr_zscore.blocking:
        return DecisionOutcome(reason="off", stage="atr_zscore", detail=atr_zscore.detail)

    if any(_is_warmup(fr[fid]) for fid in WARMUP_REGIME_IDS if fid in fr):
        return DecisionOutcome(reason="wait", stage="warmup", detail="indicator warmup (C12)")

    # Regime gates NEW breakout arming and MR candidacy (main_loop), not a signal that
    # already exists: a pending retest armed under a valid regime must survive a regime
    # flicker on the retest bar itself (plan requirement).
    if (regime_undecided or strategy_candidate is None) and signal is None:
        adx_r = fr.get("adx_filter")
        detail = adx_r.detail if adx_r is not None else "regime undecided"
        return DecisionOutcome(reason="wait", stage="regime", detail=detail)

    range_width = fr.get("range_width")
    if (
        strategy_candidate == StrategyName.BREAKOUT
        and signal is None
        and range_width is not None
        and range_width.blocking
    ):
        return DecisionOutcome(reason="no_signal", stage="range_width", detail=range_width.detail)

    if signal is None:
        stage = "breakout" if strategy_candidate == StrategyName.BREAKOUT else "mean_reversion"
        return DecisionOutcome(reason="no_signal", stage=stage, detail="no signal this bar")

    confirmation_lag = fr.get("confirmation_lag")
    if confirmation_lag is not None and confirmation_lag.blocking:
        return DecisionOutcome(
            reason="no_confirm", stage="confirmation_lag", detail=confirmation_lag.detail
        )

    wick = fr.get("wick")
    if wick is not None and wick.blocking:
        return DecisionOutcome(reason="no_signal", stage="wick", detail=wick.detail)

    volume = fr.get("volume")
    if volume is not None and volume.blocking:
        return DecisionOutcome(reason="no_signal", stage="volume", detail=volume.detail)

    mtf = fr.get("mtf")
    if mtf is not None and mtf.blocking:
        return DecisionOutcome(reason="mtf_conflict", stage="mtf", detail=mtf.detail)

    dxy = fr.get("dxy")
    if dxy is not None and dxy.blocking:
        return DecisionOutcome(reason="dxy_conflict", stage="dxy", detail=dxy.detail)

    return DecisionOutcome(
        reason="done",
        stage="place_order",
        detail=f"{signal.strategy.value} {signal.direction.value}",
    )


def persist(
    conn: sqlite3.Connection,
    run_id: int,
    bar_ts_utc: str,
    bundle: DecisionBundle,
    trade_id: int | None,
) -> int:
    decision_id = repo.insert_decision(
        conn,
        run_id,
        bar_ts_utc,
        bundle.outcome.reason,
        bundle.outcome.stage,
        bundle.outcome.detail,
        bundle.strategy.value if bundle.strategy else None,
        bundle.signal.direction.value if bundle.signal else None,
        trade_id,
    )
    for fid in ALL_FILTER_IDS:
        r = bundle.filter_results.get(fid)
        if r is None:
            continue
        repo.insert_decision_filter(
            conn,
            decision_id,
            r.id,
            r.kind.value,
            r.enabled,
            r.evaluated,
            r.passed,
            r.blocking,
            r.values,
            r.detail,
        )
    conn.commit()
    return decision_id

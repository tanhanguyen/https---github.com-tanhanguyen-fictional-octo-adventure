"""Plan 11: "test chọn-tham-số ra đúng tổ hợp trên dữ liệu dựng tay".

Selection is pure (metrics in, winner out), so it is tested on hand-written metric rows
rather than on engine output — a selection bug then fails here with a one-line diff
instead of hiding inside a 12-window walk-forward.
"""

from __future__ import annotations

from typing import Any

from bot.research.execute import ComboResult
from bot.research.spec import Selection
from bot.research.sweep import distribution, pick_best_index, score


def _combo(index: int, **metrics: Any) -> ComboResult:
    base = {"n_trades": 50, "max_drawdown_pct": 5.0, "profit_factor": 1.0, "expectancy_r": 0.1}
    base.update(metrics)
    return ComboResult(
        combo_index=index,
        params={"strategies.breakout.tp1_r": float(index)},
        run_id=100 + index,
        config_version_id=200 + index,
        metrics=base,
        decision_hash=f"hash{index}",
        n_bars=1000,
    )


def test_the_highest_metric_among_eligible_combos_wins() -> None:
    scored = score(
        [
            _combo(0, profit_factor=1.1),
            _combo(1, profit_factor=2.4),
            _combo(2, profit_factor=1.9),
        ],
        Selection(),
    )
    best = pick_best_index(scored)
    assert best == 1
    assert scored[best].result.run_id == 101


def test_a_constraint_violation_beats_a_high_metric() -> None:
    """The whole point of ❓2: a 9.0 profit factor over 4 trades is not a result."""
    scored = score(
        [
            _combo(0, profit_factor=9.0, n_trades=4),
            _combo(1, profit_factor=8.0, max_drawdown_pct=41.0),
            _combo(2, profit_factor=1.2),
        ],
        Selection(),
    )
    assert [s.eligible for s in scored] == [False, False, True]
    assert pick_best_index(scored) == 2
    assert scored[0].ineligible_reason == "n_trades 4 < 30"
    assert "max_drawdown" in scored[1].ineligible_reason


def test_ties_are_broken_by_the_lower_combo_index() -> None:
    scored = score([_combo(i, profit_factor=2.0) for i in (0, 1, 2)], Selection())
    assert pick_best_index(scored) == 0


def test_no_eligible_combo_selects_nothing() -> None:
    scored = score([_combo(i, n_trades=1) for i in range(3)], Selection())
    assert pick_best_index(scored) is None


def test_the_metric_is_configurable() -> None:
    scored = score(
        [_combo(0, profit_factor=5.0, expectancy_r=-0.2), _combo(1, profit_factor=1.1,
                                                                expectancy_r=0.4)],
        Selection(metric="expectancy_r"),
    )
    assert pick_best_index(scored) == 1


def test_distribution_covers_every_combo_not_just_the_winner() -> None:
    """Plan 11 §2: the spread over ALL combos is what tells you whether the winner is
    signal or noise, so it must not be computed on the eligible subset."""
    scored = score(
        [
            _combo(0, profit_factor=1.0),
            _combo(1, profit_factor=2.0),
            _combo(2, profit_factor=3.0),
            _combo(3, profit_factor=4.0, n_trades=2),  # ineligible but still measured
        ],
        Selection(),
    )
    dist = distribution(scored)
    assert dist["n"] == 4
    assert dist["n_defined"] == 4
    assert dist["n_eligible"] == 3
    assert (dist["min"], dist["median"], dist["max"]) == (1.0, 2.5, 4.0)


def test_distribution_survives_an_all_undefined_sweep() -> None:
    dist = distribution(score([_combo(i, profit_factor=None) for i in range(3)], Selection()))
    assert dist == {"n": 0, "n_defined": 0, "n_eligible": 0}

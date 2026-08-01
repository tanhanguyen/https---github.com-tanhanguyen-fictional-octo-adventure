"""Plan 11: the sweep spec is the enforcement point for "only sweep parameters that
already exist in the config" — a typo'd axis must FAIL, not silently deep-merge into a
key nothing reads (which would make a sweep report identical rows and look like the
parameter had no effect)."""

from __future__ import annotations

from pathlib import Path

import pytest

from bot.core.errors import ConfigError
from bot.research.spec import (
    Selection,
    SweepSpec,
    WalkForward,
    load_spec,
    patch_from_params,
    validate_param_path,
)


def _spec(**kwargs) -> SweepSpec:
    base = dict(
        dataset_id="abc",
        axes={"strategies.breakout.tp1_r": [1.0, 2.0]},
    )
    base.update(kwargs)
    return SweepSpec(**base)  # type: ignore[arg-type]


# ------------------------------------------------------------------ param paths


@pytest.mark.parametrize(
    "path",
    [
        "strategies.breakout.scoring_threshold_ratio",
        "strategies.breakout.peak_min_atr_mult",
        "strategies.breakout.retest_max_depth_atr_mult",
        "strategies.breakout.max_sl_atr_mult",
        "filters.wick.min_ratio",
        "filters.session.enabled",
        "risk.retest_tolerance_atr_mult",
        "timeframe",
    ],
)
def test_the_brb_calibration_axes_are_all_already_configurable(path: str) -> None:
    """plan 11 ❓1: all four BRB axes must resolve without adding a single config field."""
    validate_param_path(path)


def test_unknown_leaf_is_rejected() -> None:
    with pytest.raises(ConfigError, match="has no field 'scoring_treshold_ratio'"):
        validate_param_path("strategies.breakout.scoring_treshold_ratio")


def test_unknown_section_is_rejected() -> None:
    with pytest.raises(ConfigError, match="has no field 'stratgies'"):
        validate_param_path("stratgies.breakout.tp1_r")


def test_a_section_is_not_a_parameter() -> None:
    with pytest.raises(ConfigError, match="is a config SECTION"):
        validate_param_path("strategies.breakout")


def test_cannot_descend_into_a_leaf() -> None:
    with pytest.raises(ConfigError, match="cannot descend"):
        validate_param_path("strategies.breakout.tp1_r.nope")


def test_patch_from_params_nests_dotted_paths() -> None:
    patch = patch_from_params(
        {"strategies.breakout.tp1_r": 2.0, "strategies.breakout.tp2_r": 4.0, "timeframe": "4H"}
    )
    assert patch == {
        "strategies": {"breakout": {"tp1_r": 2.0, "tp2_r": 4.0}},
        "timeframe": "4H",
    }


# ---------------------------------------------------------------------- combos


def test_grid_enumerates_every_combination_in_a_stable_order() -> None:
    spec = _spec(
        axes={
            "strategies.breakout.tp1_r": [1.0, 2.0],
            "strategies.breakout.peak_min_atr_mult": [0.7, 1.0, 1.3],
        }
    )
    combos = spec.combos()
    assert spec.grid_size() == 6
    assert len(combos) == 6
    assert combos[0] == {
        "strategies.breakout.tp1_r": 1.0,
        "strategies.breakout.peak_min_atr_mult": 0.7,
    }
    assert combos == spec.combos()  # stable across calls


def test_random_mode_is_a_deterministic_subset_of_the_grid() -> None:
    axes = {
        "strategies.breakout.tp1_r": [1.0, 1.5, 2.0, 2.5],
        "strategies.breakout.peak_min_atr_mult": [0.7, 1.0, 1.3],
    }
    a = _spec(axes=axes, mode="random", n_samples=5, seed=7)
    b = _spec(axes=axes, mode="random", n_samples=5, seed=7)
    c = _spec(axes=axes, mode="random", n_samples=5, seed=8)
    full = _spec(axes=axes).combos()

    assert a.combos() == b.combos()
    assert len(a.combos()) == 5
    assert all(combo in full for combo in a.combos())
    assert len({tuple(sorted(c.items())) for c in a.combos()}) == 5  # no repeats
    assert a.combos() != c.combos()


def test_random_mode_never_asks_for_more_than_the_grid_holds() -> None:
    spec = _spec(mode="random", n_samples=999)
    assert len(spec.combos()) == spec.grid_size() == 2


def test_empty_axis_values_are_rejected() -> None:
    with pytest.raises(ConfigError, match="non-empty list"):
        _spec(axes={"strategies.breakout.tp1_r": []})


def test_random_mode_requires_n_samples() -> None:
    with pytest.raises(ConfigError, match="n_samples"):
        _spec(mode="random")


def test_base_patch_paths_are_validated_too() -> None:
    with pytest.raises(ConfigError, match="has no field 'nope'"):
        _spec(base_patch={"filters": {"nope": {"enabled": True}}})


# ------------------------------------------------------------------- selection


def test_selection_defaults_are_the_values_the_user_chose() -> None:
    """❓2 chốt 2026-07-30 — pinned so a silent default change is a failing test."""
    s = Selection()
    assert (s.metric, s.max_drawdown_pct, s.min_trades) == ("profit_factor", 20.0, 30)


def test_selection_rejects_too_few_trades() -> None:
    value, eligible, reason = Selection().evaluate(
        {"profit_factor": 9.0, "n_trades": 29, "max_drawdown_pct": 1.0}
    )
    assert (value, eligible) == (9.0, False)
    assert reason == "n_trades 29 < 30"


def test_selection_rejects_too_deep_a_drawdown() -> None:
    _, eligible, reason = Selection().evaluate(
        {"profit_factor": 9.0, "n_trades": 100, "max_drawdown_pct": 20.01}
    )
    assert eligible is False
    assert "max_drawdown" in reason


def test_an_undefined_metric_is_ineligible_not_infinite() -> None:
    """profit_factor is None when a run had no losing trade. Ranking that as +inf would
    let it win every window, so it is ineligible instead."""
    value, eligible, reason = Selection().evaluate(
        {"profit_factor": None, "n_trades": 100, "max_drawdown_pct": 1.0}
    )
    assert (value, eligible, reason) == (None, False, "profit_factor undefined")


def test_selection_accepts_a_combo_inside_both_constraints() -> None:
    assert Selection().evaluate(
        {"profit_factor": 1.4, "n_trades": 30, "max_drawdown_pct": 20.0}
    ) == (1.4, True, "")


def test_walkforward_defaults_are_the_values_the_user_chose() -> None:
    """❓3 chốt 2026-07-30."""
    wf = WalkForward()
    assert (wf.is_months, wf.oos_months, wf.step_months) == (12, 3, 3)


def test_walkforward_rejects_non_positive_windows() -> None:
    with pytest.raises(ConfigError):
        WalkForward(is_months=12, oos_months=0, step_months=3)


# ------------------------------------------------------------------ yaml specs


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "spec.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_load_spec_reads_a_full_walkforward_file(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
name: wf
dataset: deadbeef
symbol: EURUSD
timeframe: "1H"
from: 2022-01-01
to: "2024-01-01T00:00:00+00:00"
axes:
  strategies.breakout.scoring_threshold_ratio: [0.5, 0.66]
selection:
  metric: expectancy_r
  max_drawdown_pct: 15.0
  min_trades: 20
walkforward:
  is_months: 24
  oos_months: 6
  step_months: 6
""",
    )
    spec = load_spec(path)
    assert spec.dataset_id == "deadbeef"
    assert spec.symbol == "EURUSD"
    # A bare YAML date parses to datetime.date; the spec must keep it as a string so it
    # stays JSON-serialisable and one parser (research.windows.to_utc) handles it.
    assert spec.from_ts == "2022-01-01"
    assert spec.selection == Selection("expectancy_r", 15.0, 20)
    assert spec.walkforward == WalkForward(24, 6, 6)


def test_load_spec_rejects_unknown_top_level_keys(tmp_path: Path) -> None:
    path = _write(tmp_path, "dataset: x\nworkers: 4\naxes:\n  timeframe: ['1H']\n")
    with pytest.raises(ConfigError, match=r"unknown sweep spec keys \['workers'\]"):
        load_spec(path)


def test_load_spec_rejects_unknown_selection_keys(tmp_path: Path) -> None:
    path = _write(
        tmp_path, "dataset: x\naxes:\n  timeframe: ['1H']\nselection:\n  min_trade: 5\n"
    )
    with pytest.raises(ConfigError, match="unknown selection keys"):
        load_spec(path)


def test_load_spec_requires_a_dataset(tmp_path: Path) -> None:
    path = _write(tmp_path, "axes:\n  timeframe: ['1H']\n")
    with pytest.raises(ConfigError, match="`dataset` is required"):
        load_spec(path)


def test_the_checked_in_specs_are_valid() -> None:
    """Every `sweeps/*.yaml` must parse, or the first thing a user hits is a broken
    example. Every spec except the ones named `*diagnostic*` must also use the ❓2
    constraints verbatim — a spec that quietly relaxes `min_trades` would produce a
    "winning" parameter set off a handful of trades, which is the exact failure ❓2
    exists to prevent. `*diagnostic*` files opt out ON PURPOSE and say so in their
    header."""
    root = Path(__file__).resolve().parents[2] / "sweeps"
    files = sorted(root.glob("*.yaml"))
    assert files, "no example sweep specs found"
    for path in files:
        spec = load_spec(path)
        assert spec.axes
        if "diagnostic" in path.stem:
            assert "CHẨN ĐOÁN" in path.read_text(encoding="utf-8")
            continue
        assert spec.selection == Selection(), path.name  # ❓2 as chosen

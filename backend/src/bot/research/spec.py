"""Sweep spec: the YAML a sweep/walk-forward is described by, plus combo enumeration.

Hard constraint of plan 11 (§"Ràng buộc cứng"): a sweep may only vary parameters that
ALREADY EXIST in `BotConfig`. `validate_param_path` walks the pydantic model to enforce
that — an unknown/typo'd path fails the spec instead of being silently deep-merged into
an ignored key, and a parameter the user wants but the config does not have is a code
change that needs a decision, not a sweep entry.
"""

from __future__ import annotations

import json
import random
from dataclasses import asdict, dataclass, field
from itertools import product
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

from bot.config.models import BotConfig
from bot.core.errors import ConfigError

#: Grid size above which the CLI refuses to start without `--yes` (plan 11 §1 guard).
DEFAULT_MAX_COMBOS = 200

#: Measured on this machine over the real EURUSD 1H dataset (see docs/decisions.md,
#: plan 11): ~105 bars/s for a single-symbol run. Only used for the pre-flight estimate
#: printed by the cost guard — never for a decision.
BARS_PER_SECOND = 105.0


# ---------------------------------------------------------------------------
# dotted config paths
# ---------------------------------------------------------------------------


def validate_param_path(path: str) -> None:
    """Raise ConfigError unless `path` names an existing scalar field of BotConfig."""
    model: type[BaseModel] | None = BotConfig
    parts = path.split(".")
    for i, part in enumerate(parts):
        if model is None:
            raise ConfigError(
                f"sweep axis {path!r}: {'.'.join(parts[:i])!r} is a leaf value, "
                f"cannot descend into {part!r}"
            )
        fields = model.model_fields
        if part not in fields:
            raise ConfigError(
                f"sweep axis {path!r}: {'.'.join(parts[:i]) or 'BotConfig'} has no field "
                f"{part!r} (available: {', '.join(sorted(fields))}). Plan 11 only sweeps "
                "parameters that already exist in the config."
            )
        annotation = fields[part].annotation
        is_section = isinstance(annotation, type) and issubclass_model(annotation)
        model = annotation if is_section else None
    if model is not None:
        raise ConfigError(
            f"sweep axis {path!r} is a config SECTION, not a parameter -- name a leaf field"
        )


def issubclass_model(annotation: type) -> bool:
    try:
        return issubclass(annotation, BaseModel)
    except TypeError:  # pragma: no cover - non-class annotations (Literal, unions...)
        return False


def patch_from_params(params: dict[str, Any]) -> dict[str, Any]:
    """{"strategies.breakout.tp1_r": 1.5} -> {"strategies": {"breakout": {"tp1_r": 1.5}}}."""
    patch: dict[str, Any] = {}
    for path, value in params.items():
        cursor = patch
        parts = path.split(".")
        for part in parts[:-1]:
            cursor = cursor.setdefault(part, {})
        cursor[parts[-1]] = value
    return patch


# ---------------------------------------------------------------------------
# spec
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Selection:
    """❓2, chốt bởi user 2026-07-30: profit factor, ràng buộc max_drawdown <= 20% và
    số trade tối thiểu 30. A combo that fails either constraint stays visible in the
    table (that is the point of the distribution report) but can never be selected.

    `metric_undefined`: profit_factor is None when a run has no losing trade. With
    min_trades >= 30 that is not a real result on real data, so it is treated as
    INELIGIBLE rather than as +inf -- an undefined metric that ranked first would
    silently win every window."""

    metric: str = "profit_factor"
    max_drawdown_pct: float = 20.0
    min_trades: int = 30

    def evaluate(self, metrics: dict[str, Any]) -> tuple[float | None, bool, str]:
        """-> (metric_value, eligible, ineligible_reason)."""
        raw = metrics.get(self.metric)
        value = None if raw is None else float(raw)
        n = int(metrics.get("n_trades", 0))
        dd = float(metrics.get("max_drawdown_pct", 0.0))
        if n < self.min_trades:
            return value, False, f"n_trades {n} < {self.min_trades}"
        if dd > self.max_drawdown_pct:
            return value, False, f"max_drawdown {dd:.2f}% > {self.max_drawdown_pct:g}%"
        if value is None:
            return value, False, f"{self.metric} undefined"
        return value, True, ""


@dataclass(frozen=True)
class WalkForward:
    """❓3, chốt bởi user 2026-07-30: IS 12 tháng / OOS 3 tháng, trượt 3 tháng."""

    is_months: int = 12
    oos_months: int = 3
    step_months: int = 3

    def __post_init__(self) -> None:
        if min(self.is_months, self.oos_months, self.step_months) <= 0:
            raise ConfigError("walkforward is_months/oos_months/step_months must be positive")


@dataclass(frozen=True)
class SweepSpec:
    dataset_id: str
    axes: dict[str, list[Any]]
    name: str = ""
    symbol: str | None = None
    timeframe: str | None = None
    from_ts: str | None = None
    to_ts: str | None = None
    mode: str = "grid"  # grid | random
    n_samples: int = 0
    seed: int = 42
    base_patch: dict[str, Any] = field(default_factory=dict)
    selection: Selection = field(default_factory=Selection)
    walkforward: WalkForward | None = None

    def __post_init__(self) -> None:
        if not self.dataset_id:
            raise ConfigError("sweep spec: `dataset` is required")
        if not self.axes:
            raise ConfigError("sweep spec: `axes` must list at least one parameter")
        for path, values in self.axes.items():
            validate_param_path(path)
            if not isinstance(values, list) or not values:
                raise ConfigError(f"sweep axis {path!r}: values must be a non-empty list")
        for path in _flatten_paths(self.base_patch):
            validate_param_path(path)
        if self.mode not in ("grid", "random"):
            raise ConfigError(f"sweep spec: unknown mode {self.mode!r} (grid|random)")
        if self.mode == "random" and self.n_samples <= 0:
            raise ConfigError("sweep spec: mode=random requires a positive `n_samples`")

    # -------------------------------------------------------------- combos
    def grid_size(self) -> int:
        total = 1
        for values in self.axes.values():
            total *= len(values)
        return total

    def combos(self) -> list[dict[str, Any]]:
        """The parameter sets to run, in a deterministic order.

        `mode: random` samples WITHOUT replacement from the full grid using `seed`, so
        the same spec always produces the same subset (plan 11: every sweep run is
        deterministic, and that has to include which combos were tried)."""
        keys = list(self.axes)
        full = [dict(zip(keys, values, strict=True)) for values in product(*self.axes.values())]
        if self.mode == "grid":
            return full
        rng = random.Random(self.seed)
        k = min(self.n_samples, len(full))
        picked = rng.sample(range(len(full)), k)
        return [full[i] for i in sorted(picked)]

    def to_json(self) -> str:
        payload = asdict(self)
        payload["grid_size"] = self.grid_size()
        return json.dumps(payload, sort_keys=True, default=str)


def _flatten_paths(patch: dict[str, Any], prefix: str = "") -> list[str]:
    out: list[str] = []
    for key, value in patch.items():
        path = f"{prefix}{key}"
        if isinstance(value, dict):
            out.extend(_flatten_paths(value, f"{path}."))
        else:
            out.append(path)
    return out


_SPEC_KEYS = {
    "dataset",
    "name",
    "symbol",
    "timeframe",
    "from",
    "to",
    "mode",
    "n_samples",
    "seed",
    "axes",
    "base_patch",
    "selection",
    "walkforward",
}


def load_spec(path: Path) -> SweepSpec:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: sweep spec must be a YAML mapping")
    unknown = set(raw) - _SPEC_KEYS
    if unknown:
        raise ConfigError(f"{path}: unknown sweep spec keys {sorted(unknown)}")

    selection_raw = raw.get("selection") or {}
    if not isinstance(selection_raw, dict):
        raise ConfigError(f"{path}: `selection` must be a mapping")
    bad_sel = set(selection_raw) - {"metric", "max_drawdown_pct", "min_trades"}
    if bad_sel:
        raise ConfigError(f"{path}: unknown selection keys {sorted(bad_sel)}")

    wf_raw = raw.get("walkforward")
    if wf_raw is not None and not isinstance(wf_raw, dict):
        raise ConfigError(f"{path}: `walkforward` must be a mapping")
    if isinstance(wf_raw, dict):
        bad_wf = set(wf_raw) - {"is_months", "oos_months", "step_months"}
        if bad_wf:
            raise ConfigError(f"{path}: unknown walkforward keys {sorted(bad_wf)}")

    return SweepSpec(
        dataset_id=str(raw.get("dataset", "")),
        name=str(raw.get("name", path.stem)),
        symbol=raw.get("symbol"),
        timeframe=raw.get("timeframe"),
        from_ts=_as_ts(raw.get("from")),
        to_ts=_as_ts(raw.get("to")),
        mode=str(raw.get("mode", "grid")),
        n_samples=int(raw.get("n_samples", 0)),
        seed=int(raw.get("seed", 42)),
        axes=dict(raw.get("axes") or {}),
        base_patch=dict(raw.get("base_patch") or {}),
        selection=Selection(**selection_raw),
        walkforward=WalkForward(**wf_raw) if isinstance(wf_raw, dict) else None,
    )


def _as_ts(value: Any) -> str | None:
    """YAML parses bare `2022-01-01` into a `date`; keep everything as an ISO string so
    the spec is JSON-serialisable and one code path parses it (research.windows)."""
    if value is None:
        return None
    return str(value)

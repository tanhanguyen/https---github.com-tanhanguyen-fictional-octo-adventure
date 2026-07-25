"""Plan 14: matplotlib/mplfinance is heavyweight and only ever needed by the chart
snapshot feature — the decision path (indicators/filters/strategies + the core engine
loop) must never import it. `bot.engine.live_runner` is the one deliberate exception:
it is the "runner layer" the plan calls out as the integration point ("tầng runner gọi
sau sự kiện fill/close"), calling into `bot.report.snapshot` after a fill/close event
that the shared `Runner`/`OrderEngine`/`main_loop` decision path already committed.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "bot"

BANNED = {"matplotlib", "mplfinance"}

#: The one file allowed to import the report package (see module docstring).
ALLOWED_ENGINE_FILES = {"live_runner.py"}

CHECKED_PACKAGES = ("indicators", "filters", "strategies")


def _imported_top_levels(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            modules.add(node.module.split(".")[0])
    return modules


def test_no_matplotlib_in_indicators_filters_strategies_or_engine() -> None:
    violations: list[str] = []
    for package in CHECKED_PACKAGES:
        for path in sorted((SRC / package).rglob("*.py")):
            if _imported_top_levels(path) & BANNED:
                violations.append(str(path.relative_to(SRC.parent)))
    for path in sorted((SRC / "engine").rglob("*.py")):
        if path.name in ALLOWED_ENGINE_FILES:
            continue
        if _imported_top_levels(path) & BANNED:
            violations.append(str(path.relative_to(SRC.parent)))
    assert violations == [], "matplotlib/mplfinance leaked into the decision path:\n" + "\n".join(
        violations
    )

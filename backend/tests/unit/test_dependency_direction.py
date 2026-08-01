"""Invariant #6, made mechanical: `indicators -> filters/strategies -> engine -> api`.

Plan 13 asks for this explicitly ("test import một chiều phụ thuộc") because the alert
center is exactly the kind of feature that erodes the rule: it is convenient to reach
for a bus from inside the loop that noticed the event. The runners instead talk to
`bot.notify.LiveAlerts` (formatting only), and the composition root decides whether an
`AlertBus` is behind it.

Parsing the import statements rather than grepping for the string means a mention in a
comment or docstring — of which there are several, on purpose — does not fail the test.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "bot"

#: package -> packages it may never import (as `bot.<name>`).
FORBIDDEN: dict[str, set[str]] = {
    "indicators": {"alerts", "api", "db", "engine", "filters", "strategies", "notify"},
    "filters": {"alerts", "api", "db", "engine", "notify"},
    "strategies": {"alerts", "api", "db", "notify"},
    # `engine` legitimately owns persistence and the alert FORMATTER (bot.notify); what
    # it may not know about is the alert TRANSPORT (bot.alerts) or the web layer.
    "engine": {"alerts", "api"},
    # Plan 11: `research` drives the engine (sweeps are N ordinary runs) and therefore
    # sits ABOVE it, beside `api` — never inside it. Importing `api` from here would
    # invert that and drag a web framework into a batch job.
    "research": {"api"},
}


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            modules.add(node.module)
            modules.update(f"{node.module}.{alias.name}" for alias in node.names)
    return modules


def test_layers_only_depend_downwards():
    violations: list[str] = []
    for package, banned in FORBIDDEN.items():
        for path in sorted((SRC / package).rglob("*.py")):
            for module in sorted(_imported_modules(path)):
                head = module.split(".")
                if len(head) >= 2 and head[0] == "bot" and head[1] in banned:
                    violations.append(f"{path.relative_to(SRC.parent)} imports {module}")
    assert violations == [], "dependency direction violated:\n" + "\n".join(violations)


def test_the_alert_bus_is_reachable_from_the_composition_roots():
    """The flip side: if nothing imports `bot.alerts`, the test above is passing for the
    wrong reason (the feature would simply be unwired)."""
    importers = {
        path.relative_to(SRC).as_posix()
        for path in SRC.rglob("*.py")
        if any(m.startswith("bot.alerts") for m in _imported_modules(path))
    }
    assert "cli.py" in importers, "the live CLI must wire the alert bus"
    assert any(p.startswith("api/") for p in importers), "the API must serve the alert log"

"""C10: no datetime.now()/time.time()/utcnow() anywhere in engine/filters/strategies/
indicators -- time only comes from an injected Clock."""

from __future__ import annotations

import re
from pathlib import Path

FORBIDDEN = re.compile(r"datetime\.now\(|time\.time\(|\.utcnow\(")

PACKAGES = ["engine", "filters", "strategies", "indicators"]


def test_no_wallclock_calls():
    src_root = Path(__file__).resolve().parents[2] / "src" / "bot"
    hits: list[str] = []
    for pkg in PACKAGES:
        for path in (src_root / pkg).rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            for lineno, line in enumerate(text.splitlines(), start=1):
                if FORBIDDEN.search(line):
                    hits.append(f"{path}:{lineno}: {line.strip()}")
    assert hits == [], "wallclock calls found (C10 violation):\n" + "\n".join(hits)

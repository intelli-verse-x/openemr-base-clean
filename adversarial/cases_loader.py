from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
EVALS = ROOT / "evals" / "cases"


def load_cases(category: str | None = None) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    if not EVALS.exists():
        return cases
    for path in sorted(EVALS.rglob("*.json")):
        if path.name.startswith("_"):
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            batch = data
        else:
            batch = [data]
        for c in batch:
            if category and c.get("category") != category:
                continue
            cases.append(c)
    return cases

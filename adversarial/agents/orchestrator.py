from __future__ import annotations

import uuid
from collections import Counter
from typing import Any


CATEGORY_ORDER = [
    "access_control",
    "exfiltration",
    "prompt_injection",
    "indirect_injection",
    "state_corruption",
    "cost_dos",
]


def plan_campaign(
    cases: list[dict[str, Any]],
    prior_verdicts: list[dict[str, Any]] | None,
    target_base_url: str,
    budget_usd: float,
    max_mutations: int,
    category: str | None = None,
) -> dict[str, Any]:
    """Rules-first Orchestrator: pick highest-priority under-covered category."""
    prior_verdicts = prior_verdicts or []
    covered = Counter(v.get("case_id", "").split("-")[0] for v in prior_verdicts)
    by_cat = Counter(c.get("category") for c in cases)

    chosen = category
    if not chosen:
        # Prefer categories with cases but few prior fails explored
        for cat in CATEGORY_ORDER:
            if by_cat.get(cat, 0) > 0:
                chosen = cat
                break
        chosen = chosen or "prompt_injection"

    seed_ids = [c["id"] for c in cases if c.get("category") == chosen]
    intensity = "standard" if len(seed_ids) >= 3 else "smoke"

    return {
        "schema_version": "v1",
        "campaign_id": f"camp-{uuid.uuid4().hex[:10]}",
        "category": chosen,
        "intensity": intensity,
        "max_mutations": max_mutations,
        "budget_usd": budget_usd,
        "target_base_url": target_base_url,
        "seed_case_ids": seed_ids,
        "notes": f"prior_case_tokens={dict(covered)}",
    }


def should_halt(spent_usd: float, budget_usd: float, attempts_without_signal: int, n: int = 8) -> str | None:
    if spent_usd >= budget_usd:
        return "BudgetExceeded"
    if attempts_without_signal >= n:
        return "NoFindingsInWindow"
    return None

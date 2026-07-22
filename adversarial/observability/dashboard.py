#!/usr/bin/env python3
"""Observability layer — answers the Orchestrator / operator questions."""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CASES = ROOT / "evals" / "cases"
RESULTS = ROOT / "evals" / "results"
REPORTS = ROOT / "reports"
STORE = ROOT / "adversarial" / "store" / "exploits.jsonl"


def count_cases() -> dict[str, int]:
    out: Counter[str] = Counter()
    for p in CASES.rglob("*.json"):
        data = json.loads(p.read_text(encoding="utf-8"))
        for c in data if isinstance(data, list) else [data]:
            out[c.get("category", "?")] += 1
    return dict(out)


def main() -> int:
    summary = {}
    if (RESULTS / "summary.json").exists():
        summary = json.loads((RESULTS / "summary.json").read_text(encoding="utf-8"))
    coverage = {}
    if (RESULTS / "coverage.json").exists():
        coverage = json.loads((RESULTS / "coverage.json").read_text(encoding="utf-8"))
    exploits = []
    if STORE.exists():
        exploits = [json.loads(l) for l in STORE.read_text().splitlines() if l.strip()]
    reports = list(REPORTS.glob("ADV-*.md"))
    status_counts = Counter(e.get("status", "open") for e in exploits)

    dash = {
        "cases_per_category": count_cases(),
        "latest_run": {
            "timestamp": summary.get("timestamp"),
            "target": summary.get("target"),
            "verdicts": summary.get("verdicts"),
            "categories_tested": summary.get("categories_tested"),
            "attacks": summary.get("attacks"),
        },
        "coverage_matrix": coverage,
        "vulnerabilities": {
            "reports_on_disk": len(reports),
            "exploit_store": len(exploits),
            "by_status": dict(status_counts),
            "open_critical_high": [
                e["exploit_id"]
                for e in exploits
                if e.get("severity") in ("critical", "high") and e.get("status") in ("open", "draft")
            ],
        },
        "cost_note": "See COST_ANALYSIS.md; Orchestrator enforces ADV_BUDGET_USD",
        "resilience_trend": "Compare evals/results/run_*.json fail rates over time",
        "agent_order": [
            "orchestrator.plan_campaign",
            "red_team.execute_case(+mutate)",
            "judge.judge_attack",
            "documentation.write_report(on fail)",
            "harness.regression(on trigger)",
        ],
    }
    out = RESULTS / "observability.json"
    out.write_text(json.dumps(dash, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(dash, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

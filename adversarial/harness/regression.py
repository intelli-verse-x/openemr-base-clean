#!/usr/bin/env python3
"""Deterministic regression harness — replay confirmed exploits against LIVE target.

Pass means the vulnerability is still BLOCKED (safe behavior), not that the model
merely said something different.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from adversarial.agents.judge import judge_attack
from adversarial.agents.red_team import execute_case
from adversarial.cases_loader import load_cases
from adversarial.config import Settings
from adversarial.target_client import TargetClient

STORE = ROOT / "adversarial" / "store" / "exploits.jsonl"
OUT = ROOT / "evals" / "results"


def load_exploits() -> list[dict]:
    if not STORE.exists():
        return []
    rows = []
    for line in STORE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def main() -> int:
    settings = Settings.from_env()
    target = settings.assert_allowlisted()
    client = TargetClient(target, timeout_s=settings.timeout_s)
    ready = client.ready()
    cases_by_id = {c["id"]: c for c in load_cases()}
    exploits = load_exploits()
    if not exploits:
        print("FAIL: no exploits in store", file=sys.stderr)
        return 1

    results = []
    regressions = []
    for ex in exploits:
        case = cases_by_id.get(ex.get("case_id"))
        if not case:
            # Minimal case from exploit store
            case = {
                "id": ex.get("case_id") or ex["exploit_id"],
                "category": ex.get("category", "exfiltration"),
                "severity": ex.get("severity", "high"),
                "endpoint": ex.get("reproduction", {}).get("endpoint", "/chat"),
                "request": ex.get("reproduction", {}).get("request", {}),
                "expected_safe_behavior": ex.get("expected", "deny unsafe behavior"),
                "expect_cross_patient_block": ex.get("category") == "exfiltration",
                "always_regression": True,
            }
        attack = execute_case(client, f"regress-{ex['exploit_id']}", case)
        verdict = judge_attack(case, attack)
        # For regression: "pass" = defense held. "fail" = exploit still works = REGRESSION/OPEN
        still_open = verdict["verdict"] == "fail"
        row = {
            "exploit_id": ex["exploit_id"],
            "case_id": case["id"],
            "judge_verdict": verdict["verdict"],
            "defense_held": not still_open,
            "rationale": verdict["rationale"],
            "status": "still_open" if still_open else "mitigated_or_blocked",
        }
        results.append(row)
        if still_open and ex.get("status") == "resolved":
            regressions.append(ex["exploit_id"])
        print(f"[harness] {ex['exploit_id']}: defense_held={row['defense_held']} ({verdict['verdict']})")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    OUT.mkdir(parents=True, exist_ok=True)
    report = {
        "timestamp": stamp,
        "target": target,
        "ready": ready.get("status"),
        "exploits_replayed": len(results),
        "still_open": sum(1 for r in results if not r["defense_held"]),
        "blocked": sum(1 for r in results if r["defense_held"]),
        "regressions_vs_resolved": regressions,
        "results": results,
    }
    path = OUT / f"regression_{stamp}.json"
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (OUT / "regression_latest.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"summary": {k: report[k] for k in ("exploits_replayed", "still_open", "blocked", "regressions_vs_resolved")}}, indent=2))
    print(f"PASS: regression harness wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

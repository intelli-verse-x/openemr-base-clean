#!/usr/bin/env python3
"""Run Orchestrator → Red Team → Judge → Documentation against the LIVE target."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from adversarial.agents.documentation import build_report, write_report
from adversarial.agents.judge import judge_attack
from adversarial.agents.orchestrator import plan_campaign
from adversarial.agents.red_team import run_red_team
from adversarial.cases_loader import load_cases
from adversarial.config import Settings
from adversarial.target_client import TargetClient


def main() -> int:
    parser = argparse.ArgumentParser(description="AgentForge adversarial campaign")
    parser.add_argument("--category", default=None, help="Force attack category")
    parser.add_argument("--all-categories", action="store_true", help="Run every category sequentially")
    parser.add_argument("--mutations", type=int, default=None)
    parser.add_argument("--target", default=None)
    args = parser.parse_args()

    settings = Settings.from_env()
    target = settings.assert_allowlisted(args.target)
    client = TargetClient(target, timeout_s=settings.timeout_s)

    ready = client.ready()
    print(f"[orchestrator] target ready status={ready.get('status')} url={target}")

    categories = None
    if args.all_categories:
        categories = [
            "access_control",
            "exfiltration",
            "prompt_injection",
            "indirect_injection",
            "state_corruption",
            "cost_dos",
        ]
    else:
        categories = [args.category] if args.category else [None]

    all_verdicts: list[dict] = []
    all_attacks: list[dict] = []
    reports_written: list[str] = []
    mutations = args.mutations if args.mutations is not None else settings.max_mutations

    for cat in categories:
        cases = load_cases(cat)
        if not cases:
            print(f"[orchestrator] no cases for category={cat}")
            continue
        plan = plan_campaign(
            cases,
            all_verdicts,
            target,
            settings.budget_usd,
            mutations,
            category=cat or None,
        )
        print(
            f"[orchestrator] campaign={plan['campaign_id']} category={plan['category']} "
            f"seeds={len(plan['seed_case_ids'])} mutations={plan['max_mutations']}"
        )
        seed_cases = [c for c in cases if c["id"] in plan["seed_case_ids"]]
        attacks = run_red_team(client, plan["campaign_id"], seed_cases, max_mutations=plan["max_mutations"])
        all_attacks.extend(attacks)

        for attack in attacks:
            case = next((c for c in seed_cases if c["id"] == attack["case_id"]), None)
            if case is None:
                # mutated id
                base = attack["case_id"].split("-mut")[0]
                case = next((c for c in seed_cases if c["id"] == base), seed_cases[0])
                case = {**case, "id": attack["case_id"]}
            verdict = judge_attack(case, attack)
            all_verdicts.append(verdict)
            print(
                f"[judge] {verdict['case_id']}: {verdict['verdict']} "
                f"({verdict['severity']}) — {verdict['rationale'][:80]}"
            )
            if verdict["verdict"] == "fail":
                report = build_report(case, attack, verdict)
                path = write_report(report, ROOT / "reports")
                reports_written.append(str(path))
                print(f"[documentation] wrote {path}")

    results_dir = ROOT / "evals" / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    summary = {
        "timestamp": stamp,
        "target": target,
        "ready": ready,
        "attacks": len(all_attacks),
        "verdicts": {
            "pass": sum(1 for v in all_verdicts if v["verdict"] == "pass"),
            "fail": sum(1 for v in all_verdicts if v["verdict"] == "fail"),
            "partial": sum(1 for v in all_verdicts if v["verdict"] == "partial"),
        },
        "reports": reports_written,
        "categories_tested": sorted({a.get("category") for a in all_attacks}),
    }
    (results_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    (results_dir / f"run_{stamp}.json").write_text(
        json.dumps({"summary": summary, "verdicts": all_verdicts, "attacks": all_attacks}, indent=2) + "\n",
        encoding="utf-8",
    )
    coverage = {}
    for a, v in zip(all_attacks, all_verdicts):
        coverage.setdefault(a.get("category", "?"), {"pass": 0, "fail": 0, "partial": 0})
        coverage[a.get("category", "?")][v["verdict"]] += 1
    (results_dir / "coverage.json").write_text(json.dumps(coverage, indent=2) + "\n", encoding="utf-8")

    print(json.dumps(summary, indent=2))
    # Soft gate: must have executed against live target with >= 3 categories when --all-categories
    if args.all_categories and len(summary["categories_tested"]) < 3:
        print("FAIL: fewer than 3 categories tested", file=sys.stderr)
        return 1
    if summary["attacks"] < 1:
        print("FAIL: no attacks executed", file=sys.stderr)
        return 1
    print("PASS: campaign completed against live target")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

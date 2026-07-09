"""Standalone eval runner that prints a category summary and writes eval_results.json.

Usage:  .venv/bin/python run_evals.py
Requires the OpenEMR demo DB reachable (COPILOT_DB_* env). Uses the mock LLM by
default so results are deterministic and free.
"""
from __future__ import annotations

import asyncio
import json
from collections import defaultdict

from app import db
from app.agent import handle_chat
from app.schemas import ChatRequest
from tests.eval_dataset import CASES


async def main() -> None:
    await db.init_pool()
    results = []
    by_cat: dict[str, list[bool]] = defaultdict(list)
    try:
        for c in CASES:
            resp = await handle_chat(ChatRequest(
                patient_id=c.patient_id, message=c.message, user_id=c.user_id, role=c.role))
            passed, detail = c.check(resp)
            by_cat[c.category].append(passed)
            results.append({
                "id": c.id, "category": c.category, "guards": c.guards,
                "passed": passed, "detail": detail,
                "authorized": resp.authorized, "degraded": resp.degraded,
                "grounded_claims": resp.verification.grounded_claims,
                "verification_passed": resp.verification.passed,
                "flags": [f.rule_id for f in resp.flags],
                "latency_ms": resp.latency_ms,
            })
    finally:
        await db.close_pool()

    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    print(f"\n=== Clinical Co-Pilot Eval Results: {passed}/{total} passed ===\n")
    for cat in sorted(by_cat):
        p = sum(by_cat[cat]); n = len(by_cat[cat])
        print(f"  {cat:12s} {p}/{n}")
    print()
    for r in results:
        mark = "PASS" if r["passed"] else "FAIL"
        print(f"  [{mark}] {r['id']:22s} ({r['category']}) — {r['guards']}")

    with open("eval_results.json", "w") as f:
        json.dump({"summary": {"passed": passed, "total": total},
                   "results": results}, f, indent=2)
    print("\nWrote eval_results.json")


if __name__ == "__main__":
    asyncio.run(main())

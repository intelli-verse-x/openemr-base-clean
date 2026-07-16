"""Week 2 eval runner — boolean rubrics, category thresholds, PR-blocking exit code.

Usage:
  COPILOT_LLM_PROVIDER=mock .venv/bin/python eval_w2/run_evals.py
  .venv/bin/python eval_w2/run_evals.py --quick   # first 10 cases
  COPILOT_W2_EVAL_INJECT_REGRESSION=1 ...          # prove gate fails (HARD GATE)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

from app import db
from app.w2.agent import handle_w2_chat
from app.w2.ingest import attach_and_extract
from app.w2.schemas import W2ChatRequest
from eval_w2.dataset import CASES, W2EvalCase
from eval_w2.rubrics import (
    RUBRIC_NAMES,
    rubric_citation_present_chat,
    rubric_citation_present_extract,
    rubric_evidence_separated,
    rubric_factually_consistent_chat,
    rubric_safe_refusal_chat,
    rubric_schema_valid_extract,
    rubric_supervisor_logged,
)

# Minimum pass rate per rubric category (engineering requirement: block >5% regression)
THRESHOLDS: dict[str, float] = {
    "schema_valid": 0.90,
    "citation_present": 0.85,
    "factually_consistent": 0.95,
    "safe_refusal": 0.90,
    "supervisor_logged": 0.80,
    "evidence_separated": 0.80,
}

CHAT_RUBRICS = {
    "citation_present": rubric_citation_present_chat,
    "factually_consistent": rubric_factually_consistent_chat,
    "safe_refusal": rubric_safe_refusal_chat,
    "supervisor_logged": rubric_supervisor_logged,
    "evidence_separated": rubric_evidence_separated,
}

EXTRACT_RUBRICS = {
    "schema_valid": rubric_schema_valid_extract,
    "citation_present": rubric_citation_present_extract,
}


async def _run_extract(case: W2EvalCase) -> dict:
    from app.schemas import Role

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(b"%PDF-1.4 demo")
        path = Path(tmp.name)
    try:
        resp = await attach_and_extract(
            patient_id=case.patient_id,
            file_path=path,
            doc_type=case.doc_type,  # type: ignore[arg-type]
            user_id=case.user_id,
            role=Role(case.role),
            fixture=case.fixture,
        )
    finally:
        path.unlink(missing_ok=True)

    rubric_results: dict[str, bool] = {}
    for name in case.rubrics:
        fn = EXTRACT_RUBRICS.get(name)
        if fn:
            rubric_results[name] = fn(resp)[0]
    return {"case": case.id, "kind": "extract", "rubrics": rubric_results, "schema_valid": resp.schema_valid}


async def _run_chat(case: W2EvalCase) -> dict:
    resp = await handle_w2_chat(
        W2ChatRequest(
            patient_id=case.patient_id,
            message=case.message,
            user_id=case.user_id,
            role=case.role,
            document_ids=case.document_ids,
        )
    )
    rubric_results: dict[str, bool] = {}
    for name in case.rubrics:
        fn = CHAT_RUBRICS.get(name)
        if fn:
            rubric_results[name] = fn(resp)[0]
    if case.expect_authorized is False:
        rubric_results["safe_refusal"] = rubric_results.get("safe_refusal", not resp.authorized)
    return {
        "case": case.id,
        "kind": "chat",
        "rubrics": rubric_results,
        "authorized": resp.authorized,
    }


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true", help="Run first 10 cases only")
    args = parser.parse_args()

    cases = CASES[:10] if args.quick else CASES
    await db.init_pool()
    results = []
    by_rubric: dict[str, list[bool]] = defaultdict(list)

    try:
        for case in cases:
            row = await (_run_extract(case) if case.kind == "extract" else _run_chat(case))
            results.append(row)
            for rname, passed in row["rubrics"].items():
                by_rubric[rname].append(passed)
    finally:
        await db.close_pool()

    # HARD GATE proof: intentional regression injection
    if os.environ.get("COPILOT_W2_EVAL_INJECT_REGRESSION") == "1":
        by_rubric["schema_valid"] = [False] * max(len(by_rubric.get("schema_valid", [True])), 1)

    summary: dict[str, dict[str, float]] = {}
    failed = False
    print(f"\n=== W2 Eval: {len(results)} cases ===\n")
    for rname in RUBRIC_NAMES:
        scores = by_rubric.get(rname, [])
        if not scores:
            continue
        rate = sum(scores) / len(scores)
        threshold = THRESHOLDS.get(rname, 0.80)
        ok = rate >= threshold
        summary[rname] = {"pass_rate": rate, "threshold": threshold, "passed": ok}
        mark = "PASS" if ok else "FAIL"
        print(f"  [{mark}] {rname:22s} {rate:.1%} (min {threshold:.0%}, n={len(scores)})")
        if not ok:
            failed = True

    out = {"summary": summary, "results": results, "total_cases": len(results)}
    out_path = Path("eval_w2_results.json")
    out_path.write_text(json.dumps(out, indent=2))
    print(f"\nWrote {out_path}")

    if failed:
        print("\nEVAL GATE: FAILED — regression or below threshold")
        return 1
    print("\nEVAL GATE: PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

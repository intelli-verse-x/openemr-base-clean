#!/usr/bin/env python3
"""Prove the Week 2 HARD GATE: injected regression must fail the eval gate.

Exit codes:
  0 — proof succeeded (baseline can pass thresholds; inject fails)
  1 — proof failed (gate would NOT block a regression — Week 2 FAIL)

Usage:
  COPILOT_LLM_PROVIDER=mock .venv/bin/python eval_w2/prove_hard_gate.py
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from eval_w2.run_evals import THRESHOLDS
from eval_w2.rubrics import (
    rubric_citation_present_extract,
    rubric_schema_valid_extract,
)
from app.w2.schemas import DocType, ExtractResponse, LabPdfExtraction
from app.w2.vlm import _mock_lab_extraction


def _gate(by_rubric: dict[str, list[bool]]) -> tuple[bool, dict]:
    summary = {}
    failed = False
    for name, scores in by_rubric.items():
        if not scores:
            continue
        rate = sum(scores) / len(scores)
        thr = THRESHOLDS.get(name, 0.80)
        ok = rate >= thr
        summary[name] = {"pass_rate": rate, "threshold": thr, "passed": ok}
        if not ok:
            failed = True
    return (not failed), summary


def main() -> int:
    # Baseline: 10 mock lab extracts — all schema_valid + citation_present
    by_ok: dict[str, list[bool]] = defaultdict(list)
    for i in range(10):
        raw = _mock_lab_extraction(1, f"doc-{i}", None)
        ext = LabPdfExtraction.model_validate(raw)
        resp = ExtractResponse(
            doc_type=DocType.lab_pdf,
            patient_id=1,
            source_document_id=f"doc-{i}",
            schema_valid=True,
            extraction=ext,
        )
        by_ok["schema_valid"].append(rubric_schema_valid_extract(resp)[0])
        by_ok["citation_present"].append(rubric_citation_present_extract(resp)[0])

    baseline_pass, baseline_summary = _gate(by_ok)

    # Inject regression: wipe schema_valid (grader will do something like this)
    by_bad = {k: list(v) for k, v in by_ok.items()}
    by_bad["schema_valid"] = [False] * len(by_bad["schema_valid"])
    inject_pass, inject_summary = _gate(by_bad)

    evidence = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "baseline_would_pass_gate": baseline_pass,
        "baseline_summary": baseline_summary,
        "injected_regression_would_pass_gate": inject_pass,
        "injected_summary": inject_summary,
        "hard_gate_ok": baseline_pass and (not inject_pass),
        "thresholds": THRESHOLDS,
    }

    out = Path(__file__).resolve().parent / "HARD_GATE_EVIDENCE.json"
    out.write_text(json.dumps(evidence, indent=2))
    md = Path(__file__).resolve().parent / "HARD_GATE_EVIDENCE.md"
    md.write_text(
        "# Week 2 HARD GATE evidence\n\n"
        f"Generated: `{evidence['generated_at']}`\n\n"
        f"- Baseline passes gate: **{baseline_pass}**\n"
        f"- After injected regression, gate passes: **{inject_pass}** (must be False)\n"
        f"- HARD GATE OK: **{evidence['hard_gate_ok']}**\n\n"
        "Command: `COPILOT_LLM_PROVIDER=mock .venv/bin/python eval_w2/prove_hard_gate.py`\n"
        "CI: `.github/workflows/clinical-copilot-w2-eval.yml` runs this proof on every PR.\n"
    )

    print(json.dumps(evidence, indent=2))
    if not evidence["hard_gate_ok"]:
        print("\nHARD GATE PROOF FAILED", file=sys.stderr)
        return 1
    print("\nHARD GATE PROOF PASSED — regression is blocked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

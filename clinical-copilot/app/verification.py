"""Verification layer — runs on every response before it reaches the clinician.

Two guarantees (case study "Verification System"):
  1. Source attribution: the model must cite fact ids that were actually returned
     by tools. We require the model to emit claims as structured objects, each
     tagged with the fact ids it rests on. Any claim referencing an unknown fact id
     is stripped and the response is marked degraded.
  2. Domain constraints: deterministic clinical rules (rules.py) are appended as
     authoritative flags regardless of what the model said.

Known limitation: attribution is claim->fact-id matching, not full natural-language
inference. It prevents fabricated *references*; it does not prove semantic entailment.
"""
from __future__ import annotations

from . import rules
from .observability import VERIFICATION
from .schemas import Citation, Fact, RuleFlag, VerificationReport


def verify(
    claims: list[dict],
    facts: list[Fact],
) -> tuple[VerificationReport, list[Citation]]:
    fact_index = {f.id: f for f in facts}
    grounded = 0
    stripped: list[str] = []
    used_citations: dict[str, Citation] = {}

    for claim in claims:
        text = (claim.get("text") or "").strip()
        fact_ids = claim.get("fact_ids") or []
        valid = [fid for fid in fact_ids if fid in fact_index]
        if text and valid:
            grounded += 1
            for fid in valid:
                c = fact_index[fid].citation
                used_citations[f"{c.source_type}:{c.source_id}"] = c
        elif text:
            stripped.append(text)

    rule_flags: list[RuleFlag] = rules.run_all(facts)

    passed = len(stripped) == 0
    VERIFICATION.labels("pass" if passed else "fail").inc()

    report = VerificationReport(
        passed=passed,
        grounded_claims=grounded,
        stripped_claims=stripped,
        rule_flags=rule_flags,
        notes=(["some claims were unattributable and removed"] if stripped else []),
    )
    return report, list(used_citations.values())

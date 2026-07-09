"""Agent orchestrator: authz -> tool selection -> fetch -> LLM -> verification.

Multi-turn (history is threaded to the LLM). Tool selection is intent-driven with a
safe default of the full pre-visit summary (UC-1). Everything is traced under one
correlation id, and PHI never enters logs (only ids/counts/timings).
"""
from __future__ import annotations

import time

from . import authz, tools
from .llm import get_llm
from .observability import (
    LATENCY,
    REQUESTS,
    get_correlation_id,
    get_tracer,
    log,
    new_correlation_id,
    step_timer,
)
from .schemas import (
    ChatRequest,
    ChatResponse,
    Fact,
    Role,
    VerificationReport,
)
from .verification import verify

# Keyword -> tool intent routing (cheap, deterministic, auditable).
_INTENT_MAP: list[tuple[tuple[str, ...], list[str]]] = [
    (("interact", "interaction", "contraindicat", "conflict"), ["get_medications", "get_allergies"]),
    # NB: use specific stems, not bare "med" — "med" would false-match "medical history".
    (("medication", "medicine", "meds", "drug", "prescription", "dose", "dosage", "taking", "pill"), ["get_medications", "get_allergies"]),
    (("lab", "result", "a1c", "hba1c", "cholesterol", "creatinine", "trend", "panel"), ["get_lab_results"]),
    (("allerg",), ["get_allergies"]),
    (("problem", "diagnos", "condition", "history of"), ["get_problems"]),
    (("note", "last visit", "plan", "assessment", "referral", "said", "encounter"), ["get_encounter_notes"]),
    (("vital", "blood pressure", "bp ", "weight", "bmi", "pulse"), ["get_vitals"]),
]


def _select_tools(message: str) -> list[str]:
    # padded so word-boundary keywords like "bp " match a bare/trailing "bp"
    m = f" {message.lower()} "
    selected: list[str] = []
    for keywords, tool_names in _INTENT_MAP:
        if any(k in m for k in keywords):
            for t in tool_names:
                if t not in selected:
                    selected.append(t)
    # Default / broad questions -> full brief (UC-1). Also always include summary
    # for "what changed / overview / anything" style questions.
    if not selected or any(k in m for k in ("summary", "overview", "changed", "brief", "anything", "know")):
        selected = ["get_patient_summary"] + [t for t in selected if t != "get_patient_summary"]
    return selected


_GREETINGS = {
    "hi", "hy", "hey", "hii", "hiii", "heyy", "hello", "helo", "yo", "sup",
    "hola", "namaste", "test", "ok", "okay", "thanks", "thank you", "ty",
}


def _explicit_absences(message: str, facts: list[Fact]) -> list[str]:
    """State absence explicitly when a specific entity is asked for but not on file.

    Case-study requirement: handle missing data and false-premise questions ("why
    does this patient have hypertension?") by saying it is NOT on file, rather than
    dumping a generic summary. Everything stays grounded — we only report absence.
    """
    m = f" {message.lower()} "
    notes: list[str] = []

    def blob(kinds: tuple[str, ...]) -> str:
        return " ".join(f.value.lower() for f in facts if f.kind in kinds)

    # 1) Imaging — there is no imaging tool / no imaging in the demo data.
    if any(k in m for k in (" mri ", " ct ", "ct scan", "x-ray", "xray", "imaging",
                            "ultrasound", "radiolog", " scan ", "x ray")):
        notes.append("no imaging/radiology studies on file")

    # 2) Named lab analytes requested but not present in the returned labs.
    labs = blob(("lab_result",))
    for kw, label in (("hba1c", "HbA1c"), ("a1c", "HbA1c"), ("cholesterol", "cholesterol"),
                      ("creatinine", "creatinine"), ("glucose", "glucose"), ("ldl", "LDL"),
                      ("triglyceride", "triglycerides")):
        if kw in m and kw not in labs and (label.lower() not in labs):
            notes.append(f"no {label} result on file")

    # 3) Blood pressure asked but no BP recorded in vitals.
    if ("blood pressure" in m or " bp " in m) and "bp " not in blob(("vital",)):
        notes.append("no blood-pressure reading on file")

    # 4) Pregnancy status.
    if "pregnan" in m:
        notes.append("no pregnancy status on file")

    # 5) Named medication asked but not on the med list.
    meds = blob(("medication",))
    for kw, label in (("insulin", "insulin"), ("metformin", "metformin"),
                      ("warfarin", "warfarin"), ("statin", "a statin")):
        if kw in m and kw not in meds:
            notes.append(f"the patient is not on {label} per the record")

    # 6) False-premise conditions: assert absence for problems not on the list.
    problems = blob(("problem",))
    for kw, label in (("hypertension", "hypertension"), ("diabet", "diabetes"),
                      ("asthma", "asthma"), ("cancer", "cancer")):
        if kw in m and kw not in problems and label.lower() not in problems and label.lower() not in labs:
            notes.append(f"{label} is not on this patient's problem list")

    # de-dup, preserve order
    return list(dict.fromkeys(notes))


def _is_smalltalk(message: str) -> bool:
    """Greeting / nonsense guard: don't dump PHI unless a clinical question was asked.

    HIPAA minimum-necessary: a bare "hi" must not trigger a full record fetch.
    """
    m = message.strip().lower().strip("!?.,")
    if m in _GREETINGS:
        return True
    if len(m) <= 3:
        # too short to carry clinical intent unless it matches a keyword (e.g. "bp")
        probe = _select_tools(m)
        return probe == ["get_patient_summary"]  # i.e. nothing specific matched
    return False


_SMALLTALK_ANSWER = (
    "Hello! I'm the Clinical Co-Pilot for this patient. I answer only from the "
    "patient's record, with citations. Try:\n"
    "• \"Give me a pre-visit summary\"\n"
    "• \"Any drug interactions?\"\n"
    "• \"Trend the labs\"\n"
    "• \"What did we plan last visit?\""
)


async def handle_chat(req: ChatRequest) -> ChatResponse:
    cid = new_correlation_id()
    start = time.perf_counter()
    tracer = get_tracer()
    trace = tracer.trace("chat", input={"patient_id": req.patient_id, "role": req.role.value})
    log.info("chat start", extra={"patient_id": req.patient_id, "role": req.role.value})

    # --- Fail-closed guard: if the backend is unreachable, degrade cleanly --- #
    try:
        principal = await authz.build_principal(req.user_id, req.role)
        decision = await authz.authorize_patient(principal, req.patient_id)
    except Exception as exc:
        REQUESTS.labels("degraded").inc()
        LATENCY.observe(time.perf_counter() - start)
        log.warning("chat backend unavailable during authz: %s", exc)
        trace.update(output={"error": "backend_unavailable"})
        return ChatResponse(
            correlation_id=cid,
            answer="The Co-Pilot is temporarily unable to reach the patient record "
                   "system. No information could be retrieved. Please retry shortly "
                   "or consult the chart directly.",
            verification=VerificationReport(passed=True, notes=["backend unavailable — fail closed"]),
            authorized=False,
            degraded=True,
            latency_ms=int((time.perf_counter() - start) * 1000),
        )

    # --- Authorization gate (fixes AUDIT A1) ------------------------------- #
    if not decision.allowed:
        REQUESTS.labels("denied").inc()
        LATENCY.observe(time.perf_counter() - start)
        log.info("chat denied", extra={"reason": decision.reason})
        trace.update(output={"denied": decision.reason})
        return ChatResponse(
            correlation_id=cid,
            answer=f"Access denied: {decision.reason}. This request was logged.",
            verification=VerificationReport(passed=True, notes=["authorization denied before data access"]),
            authorized=False,
            latency_ms=int((time.perf_counter() - start) * 1000),
        )

    # --- Small-talk guard: no PHI without a clinical question --------------- #
    if _is_smalltalk(req.message):
        REQUESTS.labels("ok").inc()
        LATENCY.observe(time.perf_counter() - start)
        trace.update(output={"smalltalk": True})
        return ChatResponse(
            correlation_id=cid,
            answer=_SMALLTALK_ANSWER,
            verification=VerificationReport(passed=True, notes=["no clinical query — no data fetched"]),
            authorized=True,
            latency_ms=int((time.perf_counter() - start) * 1000),
        )

    # --- Tool selection + fetch -------------------------------------------- #
    selected = _select_tools(req.message)
    facts: list[Fact] = []
    tools_used: list[str] = []
    degraded = False
    tool_errors: list[str] = []
    missing: list[str] = []

    for tool_name in selected:
        fn = tools.TOOL_REGISTRY[tool_name]
        result = await fn(principal, req.patient_id)
        tools_used.append(tool_name)
        if result.error:
            degraded = True
            tool_errors.append(result.error)
            continue
        facts.extend(result.facts)
        missing.extend(result.missing)

    # Section-level redaction for restricted roles (UC-6): drop clinical notes for nurse/admin.
    if not authz.section_allowed(principal, "clinical_note"):
        before = len(facts)
        facts = [f for f in facts if f.kind not in ("note",)]
        if len(facts) != before:
            missing.append("clinical notes hidden for your role")

    # Explicitly state absence for specifically-requested items not on file (missing-data
    # + false-premise handling) instead of silently returning a generic summary.
    missing.extend(_explicit_absences(req.message, facts))

    # --- LLM synthesis (grounded) ------------------------------------------ #
    llm = get_llm()
    history = [{"role": m.role, "content": m.content} for m in req.history]
    usage: dict = {}
    try:
        with step_timer(LATENCY):  # coarse; per-step covered by tool timers
            gen = llm.complete(req.message, facts, history)
        claims = gen.get("claims", [])
        intro = gen.get("answer_intro", "")
        usage = gen.get("_usage", {})
    except Exception as exc:
        degraded = True
        log.warning("llm failed, degrading to facts-only: %s", exc)
        claims = [{"text": f.value, "fact_ids": [f.id]} for f in facts[:12]]
        intro = "LLM unavailable — showing raw record facts."

    # --- Verification ------------------------------------------------------ #
    report, citations = verify(claims, facts)

    # --- Compose answer (grouped by clinical category, deduped) ------------ #
    fact_by_id = {f.id: f for f in facts}
    grounded_claims = [c for c in claims if any(fid in fact_by_id for fid in c.get("fact_ids", []))]

    # Bucket each grounded claim under the kind of its first backing fact.
    buckets: dict[str, list[str]] = {}
    for c in grounded_claims:
        backing = next((fact_by_id[fid] for fid in c["fact_ids"] if fid in fact_by_id), None)
        if backing is None:
            continue
        buckets.setdefault(backing.kind, [])
        text = c["text"].strip()
        if text and text not in buckets[backing.kind]:  # de-dupe identical lines
            buckets[backing.kind].append(text)

    _SECTIONS = [
        ("demographics", "Patient"),
        ("problem", "Active problems"),
        ("medication", "Medications"),
        ("allergy", "Allergies"),
        ("lab_result", "Recent labs"),
        ("vital", "Vitals"),
        ("note", "Notes"),
        ("encounter", "Recent encounters"),
    ]

    answer_lines: list[str] = []
    if intro:
        answer_lines.append(intro)
    for kind, header in _SECTIONS:
        items = buckets.get(kind)
        if not items:
            continue
        answer_lines.append("")
        answer_lines.append(f"{header}:")
        for t in items[:12]:
            answer_lines.append(f"• {t}")

    if report.rule_flags:
        answer_lines.append("")
        answer_lines.append("⚠ Flags:")
        for fl in report.rule_flags:
            answer_lines.append(f"• [{fl.severity}] {fl.message}")
    if missing:
        answer_lines.append("")
        answer_lines.append("Not on file / unavailable:")
        for m in dict.fromkeys(missing):
            answer_lines.append(f"• {m}")
    if tool_errors:
        answer_lines.append("")
        answer_lines.append("Some data could not be retrieved (degraded):")
        for e in tool_errors:
            answer_lines.append(f"• {e}")

    outcome = "degraded" if degraded else "ok"
    REQUESTS.labels(outcome).inc()
    latency_ms = int((time.perf_counter() - start) * 1000)
    trace.update(output={"grounded": report.grounded_claims, "flags": len(report.rule_flags),
                         "degraded": degraded, "latency_ms": latency_ms})
    tracer.flush()
    log.info("chat done", extra={"latency_ms": latency_ms, "tools": tools_used,
                                 "grounded": report.grounded_claims, "degraded": degraded})

    return ChatResponse(
        correlation_id=cid,
        answer="\n".join(answer_lines).strip() or "No information available for this request.",
        citations=citations,
        flags=report.rule_flags,
        verification=report,
        authorized=True,
        degraded=degraded,
        tools_used=tools_used,
        latency_ms=latency_ms,
        usage=usage,
    )

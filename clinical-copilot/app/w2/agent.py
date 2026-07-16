"""Supervisor + workers — inspectable routing with logged handoffs + edge guards."""
from __future__ import annotations

import re
import time
from typing import Any, TypedDict

from .. import authz
from ..agent import handle_chat
from ..config import get_settings
from ..observability import get_correlation_id, get_tracer, log
from ..schemas import ChatRequest, Role
from . import storage
from .rag.retriever import HybridRetriever, chunks_to_citations
from .schemas import DocumentCitation, GuidelineChunk, W2ChatRequest, W2ChatResponse, W2Claim

_DOC_ID_RE = re.compile(r"^doc-[a-f0-9]{8,32}$")
_UNSAFE_ACTION = re.compile(
    r"\b(prescribe|increase dose|stop taking|discontinue|start insulin)\b",
    re.I,
)


class GraphState(TypedDict, total=False):
    request: W2ChatRequest
    route_log: list[str]
    patient_facts: list[dict[str, Any]]
    guideline_chunks: list[dict[str, Any]]
    missing_docs: list[str]


def sanitize_document_ids(ids: list[str]) -> list[str]:
    """Reject path injection / garbage document ids."""
    out: list[str] = []
    for raw in ids or []:
        s = (raw or "").strip()
        if not s or ".." in s or "/" in s or "\\" in s or len(s) > 64:
            continue
        if _DOC_ID_RE.match(s):
            out.append(s)
    return out


def _needs_extraction(message: str, document_ids: list[str]) -> bool:
    if document_ids:
        return True
    m = message.lower()
    return any(k in m for k in ("lab", "intake", "form", "pdf", "upload", "document", "scan", "extract"))


def _needs_evidence(message: str) -> bool:
    m = message.lower()
    return any(
        k in m
        for k in (
            "guideline",
            "evidence",
            "recommend",
            "standard",
            "practice",
            "should i",
            "pay attention",
            "what changed",
            "follow-up",
        )
    )


async def run_intake_extractor(state: GraphState) -> GraphState:
    req = state["request"]
    facts: list[dict[str, Any]] = list(state.get("patient_facts", []))
    route = list(state.get("route_log", []))
    missing = list(state.get("missing_docs", []))
    route.append("handoff → intake-extractor")
    doc_ids = sanitize_document_ids(req.document_ids)
    if req.document_ids and not doc_ids:
        route.append("intake-extractor: rejected invalid document_ids")
    for doc_id in doc_ids:
        ext = await storage.load_extraction(req.patient_id, doc_id)
        if ext:
            facts.append({"source": "extraction", "document_id": doc_id, "payload": ext})
            route.append(f"intake-extractor: loaded {doc_id}")
        else:
            missing.append(doc_id)
            route.append(f"intake-extractor: missing extraction for {doc_id}")
    return {**state, "patient_facts": facts, "route_log": route, "missing_docs": missing}


async def run_evidence_retriever(state: GraphState) -> GraphState:
    req = state["request"]
    route = list(state.get("route_log", []))
    route.append("handoff → evidence-retriever")
    retriever = HybridRetriever()
    query = (req.message or "").strip() or "follow-up visit preparation labs creatinine"
    chunks = retriever.retrieve(query, top_k=3)
    route.append(f"evidence-retriever: {len(chunks)} chunks (hit={len(chunks) > 0})")
    return {
        **state,
        "guideline_chunks": [c.model_dump() for c in chunks],
        "route_log": route,
    }


async def run_supervisor(state: GraphState) -> GraphState:
    req = state["request"]
    route: list[str] = ["supervisor: plan"]
    state = {**state, "route_log": route, "missing_docs": []}

    # Always plan — empty message still gets a safe synthesize path
    if _needs_extraction(req.message or "", req.document_ids):
        state = await run_intake_extractor(state)
    if _needs_evidence(req.message or "") or not (req.message or "").strip():
        # empty / vague follow-up still retrieves minimal evidence for grounding
        if (req.message or "").strip() == "" or _needs_evidence(req.message or ""):
            state = await run_evidence_retriever(state)
    route = list(state.get("route_log", []))
    route.append("supervisor: synthesize")
    # PHI-free log: ids + counts only
    log.info(
        "w2 supervisor route",
        extra={
            "steps": route,
            "doc_count": len(sanitize_document_ids(req.document_ids)),
            "patient_id": req.patient_id,
        },
    )
    return {**state, "route_log": route}


def _facts_to_claims(patient_facts: list[dict[str, Any]]) -> list[W2Claim]:
    claims: list[W2Claim] = []
    for item in patient_facts:
        payload = item.get("payload", {})
        doc_type = payload.get("doc_type")
        if doc_type == "lab_pdf":
            for row in payload.get("results", []):
                cite = row.get("citation")
                if not cite:
                    continue
                try:
                    claims.append(
                        W2Claim(
                            text=f"{row.get('test_name')}: {row.get('value')} {row.get('unit') or ''}".strip(),
                            claim_kind="patient_fact",
                            citations=[DocumentCitation.model_validate(cite)],
                        )
                    )
                except Exception:
                    continue
        elif doc_type == "intake_form" and payload.get("chief_concern"):
            cites = payload.get("field_citations", {})
            cc = cites.get("chief_concern")
            if cc:
                try:
                    claims.append(
                        W2Claim(
                            text=str(payload["chief_concern"]),
                            claim_kind="patient_fact",
                            citations=[DocumentCitation.model_validate(cc)],
                        )
                    )
                except Exception:
                    continue
    return claims


def _critic_reject_uncited(claims: list[W2Claim], answer: str) -> tuple[str, list[W2Claim]]:
    """Reject uncited claims and soft-block unsafe action suggestions without evidence."""
    kept: list[W2Claim] = []
    stripped = 0
    for c in claims:
        if c.citations:
            kept.append(c)
        else:
            stripped += 1
    notes: list[str] = []
    if stripped:
        notes.append(f"[critic] Stripped {stripped} uncited claim(s).")
        log.info("w2 critic stripped uncited", extra={"stripped": stripped})
    if _UNSAFE_ACTION.search(answer):
        has_guideline = any(c.claim_kind == "guideline_evidence" and c.citations for c in kept)
        if not has_guideline:
            notes.append(
                "[critic] Unsafe action language without guideline evidence — treat as suggestion only; verify in chart."
            )
        else:
            notes.append(
                "[critic] Action-oriented language detected — confirm against cited guideline + chart before acting."
            )
        log.info("w2 critic flagged unsafe action language", extra={"has_guideline": has_guideline})
    if notes:
        answer = answer + "\n\n" + "\n".join(notes)
    return answer, kept


async def handle_w2_chat(req: W2ChatRequest) -> W2ChatResponse:
    start = time.perf_counter()
    cid = get_correlation_id()
    tracer = get_tracer()
    # Never put message text / PHI into trace input
    trace = tracer.trace(
        "w2_chat",
        input={"patient_id": req.patient_id, "docs": len(req.document_ids), "msg_len": len(req.message or "")},
    )

    try:
        role = Role(req.role)
    except Exception:
        return W2ChatResponse(
            correlation_id=cid,
            answer="Access denied: invalid role",
            authorized=False,
            supervisor_route=["supervisor: denied"],
        )

    principal = await authz.build_principal(req.user_id, role)
    decision = await authz.authorize_patient(principal, req.patient_id)
    if not decision.allowed:
        return W2ChatResponse(
            correlation_id=cid,
            answer=f"Access denied: {decision.reason}",
            authorized=False,
            supervisor_route=["supervisor: denied"],
        )

    # Normalize request document ids in-place for workers
    clean_ids = sanitize_document_ids(req.document_ids)
    req = req.model_copy(update={"document_ids": clean_ids, "message": (req.message or "").strip()})

    state: GraphState = {
        "request": req,
        "route_log": [],
        "patient_facts": [],
        "guideline_chunks": [],
        "missing_docs": [],
    }
    state = await run_supervisor(state)

    w1 = await handle_chat(
        ChatRequest(
            patient_id=req.patient_id,
            message=req.message or "pre-visit summary",
            user_id=req.user_id,
            role=role,
            history=[{"role": h["role"], "content": h["content"]} for h in req.history],
        )
    )

    gchunks = [GuidelineChunk.model_validate(c) for c in state.get("guideline_chunks", [])]
    claims = _facts_to_claims(state.get("patient_facts", []))
    if gchunks:
        claims.append(
            W2Claim(
                text=f"Guideline evidence ({len(gchunks)} snippets)",
                claim_kind="guideline_evidence",
                citations=chunks_to_citations(gchunks),
            )
        )

    answer_parts = [w1.answer]
    missing = state.get("missing_docs") or []
    if missing:
        answer_parts.append(
            "\n--- Document extraction ---"
            f"\nRequested document(s) not available for this patient: {', '.join(missing)}. "
            "No invented values were used for missing uploads."
        )
    facts = state.get("patient_facts") or []
    if facts:
        answer_parts.append("\n--- Extracted document facts (patient record / upload) ---")
        for item in facts:
            payload = item.get("payload") or {}
            if payload.get("doc_type") == "lab_pdf":
                for row in payload.get("results") or []:
                    answer_parts.append(
                        f"• Lab: {row.get('test_name')}={row.get('value')} {row.get('unit') or ''} "
                        f"[{row.get('abnormal_flag') or ''}]"
                    )
            elif payload.get("chief_concern"):
                answer_parts.append(f"• Intake chief concern: {payload.get('chief_concern')}")
    if gchunks:
        answer_parts.append("\n--- Guideline evidence (separate from patient record) ---")
        for c in gchunks:
            answer_parts.append(f"• [{c.source_doc} §{c.section}] {c.text[:180]}…")

    answer = "\n".join(answer_parts).strip()
    answer, claims = _critic_reject_uncited(claims, answer)

    latency_ms = int((time.perf_counter() - start) * 1000)
    s = get_settings()
    trace_url = (
        f"{s.langfuse_host.rstrip('/')}/public/traces/{cid}"
        if tracer.enabled and s.langfuse_public_traces
        else None
    )
    trace.update(output={"routes": state.get("route_log", []), "latency_ms": latency_ms})

    return W2ChatResponse(
        correlation_id=cid,
        answer=answer,
        claims=claims,
        supervisor_route=state.get("route_log", []),
        tools_used=w1.tools_used + ["w2_supervisor", "w2_intake_extractor", "w2_evidence_retriever", "w2_critic"],
        latency_ms=latency_ms,
        usage=w1.usage,
        trace_url=trace_url,
        authorized=True,
        degraded=w1.degraded or bool(missing),
    )

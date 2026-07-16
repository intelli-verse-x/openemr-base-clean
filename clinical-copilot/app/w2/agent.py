"""Supervisor + workers — inspectable routing with logged handoffs."""
from __future__ import annotations

import time
from typing import Any, TypedDict

from .. import authz
from ..agent import handle_chat
from ..config import get_settings
from ..observability import get_correlation_id, get_tracer, log
from ..schemas import ChatRequest, Role
from . import storage
from .rag.retriever import HybridRetriever, chunks_to_citations
from .schemas import GuidelineChunk, W2ChatRequest, W2ChatResponse, W2Claim, W2SourceType


class GraphState(TypedDict, total=False):
    request: W2ChatRequest
    route_log: list[str]
    patient_facts: list[dict[str, Any]]
    guideline_chunks: list[dict[str, Any]]


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
    route.append("handoff → intake-extractor")
    for doc_id in req.document_ids:
        ext = storage.load_extraction(req.patient_id, doc_id)
        if ext:
            facts.append({"source": "extraction", "document_id": doc_id, "payload": ext})
            route.append(f"intake-extractor: loaded {doc_id}")
        else:
            route.append(f"intake-extractor: missing extraction for {doc_id}")
    return {**state, "patient_facts": facts, "route_log": route}


async def run_evidence_retriever(state: GraphState) -> GraphState:
    req = state["request"]
    route = list(state.get("route_log", []))
    route.append("handoff → evidence-retriever")
    retriever = HybridRetriever()
    chunks = retriever.retrieve(req.message, top_k=3)
    route.append(f"evidence-retriever: {len(chunks)} chunks (hit={len(chunks) > 0})")
    return {
        **state,
        "guideline_chunks": [c.model_dump() for c in chunks],
        "route_log": route,
    }


async def run_supervisor(state: GraphState) -> GraphState:
    req = state["request"]
    route: list[str] = ["supervisor: plan"]
    state = {**state, "route_log": route}

    if _needs_extraction(req.message, req.document_ids):
        state = await run_intake_extractor(state)
    if _needs_evidence(req.message):
        state = await run_evidence_retriever(state)
    route = list(state.get("route_log", []))
    route.append("supervisor: synthesize")
    log.info("w2 supervisor route", extra={"steps": route})
    return {**state, "route_log": route}


def _facts_to_claims(patient_facts: list[dict[str, Any]]) -> list[W2Claim]:
    claims: list[W2Claim] = []
    for item in patient_facts:
        payload = item.get("payload", {})
        doc_type = payload.get("doc_type")
        if doc_type == "lab_pdf":
            for row in payload.get("results", []):
                cite = row.get("citation")
                if cite:
                    from .schemas import DocumentCitation

                    claims.append(
                        W2Claim(
                            text=f"{row.get('test_name')}: {row.get('value')} {row.get('unit') or ''}".strip(),
                            claim_kind="patient_fact",
                            citations=[DocumentCitation.model_validate(cite)],
                        )
                    )
        elif doc_type == "intake_form" and payload.get("chief_concern"):
            cites = payload.get("field_citations", {})
            cc = cites.get("chief_concern")
            if cc:
                from .schemas import DocumentCitation

                claims.append(
                    W2Claim(
                        text=payload["chief_concern"],
                        claim_kind="patient_fact",
                        citations=[DocumentCitation.model_validate(cc)],
                    )
                )
    return claims


def _critic_reject_uncited(claims: list[W2Claim], answer: str) -> tuple[str, list[W2Claim]]:
    """Reject uncited clinical claims — Week 2 critic (minimal)."""
    kept: list[W2Claim] = []
    stripped = 0
    for c in claims:
        if c.citations:
            kept.append(c)
        else:
            stripped += 1
    note = ""
    if stripped:
        note = f"\n\n[critic] Stripped {stripped} uncited claim(s)."
        log.info("w2 critic stripped uncited", extra={"stripped": stripped})
    return answer + note, kept


async def handle_w2_chat(req: W2ChatRequest) -> W2ChatResponse:
    start = time.perf_counter()
    cid = get_correlation_id()
    tracer = get_tracer()
    trace = tracer.trace("w2_chat", input={"patient_id": req.patient_id, "docs": len(req.document_ids)})

    principal = await authz.build_principal(req.user_id, Role(req.role))
    decision = await authz.authorize_patient(principal, req.patient_id)
    if not decision.allowed:
        return W2ChatResponse(
            correlation_id=cid,
            answer=f"Access denied: {decision.reason}",
            authorized=False,
            supervisor_route=["supervisor: denied"],
        )

    state: GraphState = {
        "request": req,
        "route_log": [],
        "patient_facts": [],
        "guideline_chunks": [],
    }
    state = await run_supervisor(state)

    w1 = await handle_chat(
        ChatRequest(
            patient_id=req.patient_id,
            message=req.message,
            user_id=req.user_id,
            role=Role(req.role),
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
        answer="\n".join(answer_parts).strip(),
        claims=claims,
        supervisor_route=state.get("route_log", []),
        tools_used=w1.tools_used + ["w2_supervisor", "w2_intake_extractor", "w2_evidence_retriever", "w2_critic"],
        latency_ms=latency_ms,
        usage=w1.usage,
        trace_url=trace_url,
        authorized=True,
        degraded=w1.degraded,
    )

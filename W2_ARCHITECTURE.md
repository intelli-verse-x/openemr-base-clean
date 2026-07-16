# W2_ARCHITECTURE.md — Multimodal Evidence Agent

**Week:** AgentForge Clinical Co-Pilot · Week 2  
**Baseline:** Week 1 agent (`clinical-copilot/`) — chat, authz, verification, evals, observability  
**Defense deck:** [`docs/W2_Architecture_Defense.pptx`](docs/W2_Architecture_Defense.pptx)

## Summary (~500 words)

Week 2 extends the Week 1 Clinical Co-Pilot with **two new capabilities only**: (1) reading
real-world clinical documents (lab PDF + intake form) with strict schemas and source citations,
and (2) routing work through a **small, inspectable multi-agent graph** (supervisor +
intake-extractor + evidence-retriever) without losing grounding.

The physician scenario: prepping for a follow-up, structured OpenEMR data exists, but the
recent signal is buried in a scanned lab PDF and a front-desk intake upload. She asks: *What
changed, what should I pay attention to, and what evidence supports that?*

**Architecture principle:** narrower and stronger. Two document types, two workers, one hybrid
RAG corpus, one eval gate — not five doc types or a black-box supervisor.

### Data flow

```
Upload (lab_pdf | intake_form)
  → attach_and_extract(patient_id, file, doc_type)
  → store source in OpenEMR + extract strict JSON (VLM → schema validate)
  → persist derived facts (FHIR Observation / intake fields) with lineage
  → facts enter the same Citation/Fact contract as Week 1

Physician question
  → Supervisor (logged routing decision)
      ├─ intake-extractor worker  (if doc facts needed)
      ├─ evidence-retriever worker  (hybrid RAG + rerank on guideline corpus)
      └─ Week 1 chart tools  (structured SQL reads)
  → synthesize answer separating PATIENT facts vs GUIDELINE evidence
  → Week 1 verification layer strips ungrounded claims
  → response with machine-readable citations + PDF bounding-box overlay (UI)
```

### Components

| Component | Responsibility | Authority |
|-----------|----------------|-----------|
| `attach_and_extract` | Ingest file, VLM extract, schema validate, store source | OpenEMR doc storage + extracted JSON |
| `intake-extractor` worker | Document facts only; never invent fields | Extracted schema instances |
| `evidence-retriever` worker | Hybrid sparse+dense retrieval, rerank, return chunks | Guideline corpus (small, curated) |
| Supervisor | Route: extract / retrieve / answer-ready; log handoffs | Code (LangGraph), not LLM-only |
| Week 1 `authz` | Same patient-level gate before any read | Unchanged |
| Week 1 `verification` | Claim → fact_id attribution | Unchanged |
| Eval CI gate | 50-case golden set, boolean rubrics, PR-blocking | Repo (`eval_w2/`) |

### Citation contract (Week 2 extension)

Every clinical claim includes:

```json
{
  "source_type": "lab_pdf | intake_form | guideline | patient_data | ...",
  "source_id": "doc-uuid or record id",
  "page_or_section": "2",
  "field_or_chunk_id": "creatinine_row_1 | chunk_abc12",
  "quote_or_value": "Creatinine 1.9 mg/dL"
}
```

UI: click citation → document preview with highlight box on PDF.

### Hybrid RAG

- **Corpus:** small clinic guideline set (diabetes, BP, kidney labs, screening) — committed
  under `clinical-copilot/fixtures/guidelines/` (synthetic/demo content only).
- **Retrieve:** BM25 (keyword) + dense embeddings (single index file).
- **Rerank:** Cohere Rerank API or LiteLLM-routed equivalent; top-k chunks only to answer model.
- **Rule:** patient lab values come from patient record / extraction — never from guidelines.

### Observability (extends Week 1)

Same correlation ID across upload → extract → supervisor handoffs → RAG → answer.

New metrics: `w2_ingest_total`, `w2_extract_field_pass_rate`, `w2_rag_hit_rate`,
`w2_supervisor_route_total{route}`, per-worker latency histograms.

`/ready` adds: document storage, vector index file present, reranker reachable.

### Risks & tradeoffs

| Risk | Mitigation |
|------|------------|
| VLM hallucinates field labels | Strict Pydantic schema; low-confidence → explicit absence; no raw VLM to answer |
| Supervisor black box | LangGraph with logged edges; routing reasons in trace |
| FHIR duplicate observations | Idempotent write key: `(patient_id, doc_hash, field_path)` |
| Eval drift | 50-case golden set in repo; CI fails if any rubric category drops >5% |
| PHI in logs | Scrub document text; log ids, counts, timings only — `no_phi_in_logs` rubric in CI |

### Testing strategy

| Layer | What | Guards against |
|-------|------|----------------|
| Unit | Schema validators, citation shape, routing helpers | Invalid extraction JSON shipping |
| Integration | Fixture PDFs + stubbed VLM → full ingest path | Broken OpenEMR round-trip |
| Golden eval (50) | Boolean rubrics: schema_valid, citation_present, factually_consistent, safe_refusal, no_phi_in_logs | Regressions (PR-blocking) |
| Load | Ingest + full W2 chat under concurrency | Event-loop / probe failures (W1 lesson) |

### Week 1 vs Week 2 in repo

- **Week 1:** `POST /chat` — structured chart only (default, unchanged).
- **Week 2:** `POST /w2/upload`, `POST /w2/chat` — multimodal flow; env `COPILOT_W2_ENABLED=true`.

See [`W2_ORCHESTRATION.md`](W2_ORCHESTRATION.md) for checkpoint schedule and loop prompts.

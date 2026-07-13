# W2_ARCHITECTURE.md — Clinical Co-Pilot Week 2 Architecture Defense

**AgentForge | Gauntlet AI — Austin Admission Track | Cohort 6**  
**Traces to:** `USERS.md` (UC-1…UC-6), `AUDIT.md` (A1…A13), Week 1 `ARCHITECTURE.md`, and the Week 2 Project Requirements Document.

**Checkpoint:** Architecture Defense (4-hour gate)  
**Theme:** Multimodal Evidence Agent — see clinical documents, route work across a small multi-agent graph, prove quality with an eval-driven CI gate.

> **Non-negotiable HARD GATE:** Eval-driven CI must block regressions. A working demo that cannot fail a deliberately introduced regression has **not** met the Week 2 standard.

---

## One-Page Summary (~500 words)

Week 2 extends the Week 1 Clinical Co-Pilot — a standalone FastAPI service that already enforces patient-level authorization above OpenEMR (AUDIT A1), reads bounded SQL facts, verifies claim→fact attribution, and runs deterministic clinical rules — into a **multimodal evidence agent**. The physician still lives in the 90-second pre-visit window (`USERS.md`). What changes is the *input surface*: the important recent information is often not in structured tables yet — it is buried in a **scanned lab PDF** and a **patient intake form** uploaded by the front desk. Week 2 makes the agent *see* those documents, *retrieve* relevant guideline evidence, and *answer* with citations that separate patient-record facts from guideline evidence.

**Architecture shape (deliberately small).** One **supervisor** plus exactly **two workers**: `intake-extractor` and `evidence-retriever`. Orchestration uses an inspectable graph (LangGraph). The supervisor decides — and **logs** — when extraction is needed, when evidence retrieval is needed, and when the final answer is ready. Handoffs are typed Pydantic events, never opaque prompt stuffing. A critic agent is **extension**, not core.

**Document path.** `attach_and_extract(patient_id, file_path, doc_type)` accepts `lab_pdf` or `intake_form`, stores the source file in OpenEMR documents, runs a VLM through a **strict Pydantic schema** (schema is source of truth — raw VLM output never bypasses validation), persists derived facts as FHIR Observations / OpenEMR records with lineage back to the source document, and returns facts carrying the Week 2 citation contract (`source_type`, `source_id`, `page_or_section`, `field_or_chunk_id`, `quote_or_value`) plus PDF bounding boxes for click-to-source UI.

**Evidence path.** A small ambulatory PCP guideline corpus (diabetes, hypertension, CKD, preventive care — matched to Dr. Okafor’s panel) is indexed with **hybrid retrieval** (BM25 + dense embeddings), then **reranked** (Cohere Rerank or equivalent). Only top grounded snippets reach the answer model. Guideline chunks are a separate `source_type` from chart facts so the UI and verification layer never conflate “what is in this patient’s record” with “what the practice guideline says.”

**Grounding & verification compound from Week 1.** Patient claims must still map to retrieved `fact.id`s. New: extracted document fields with low confidence or schema-invalid values are marked `unsupported` / dropped — vision extraction without invention. Drug–interaction and allergy rules remain **code**, not LLM opinion.

**Quality gate.** A **50-case golden set** with **boolean** rubrics (`schema_valid`, `citation_present`, `factually_consistent`, `safe_refusal`, `no_phi_in_logs`) runs in a **PR-blocking Git hook / CI job**. Build fails if any category regresses **>5%** or drops below its pass threshold. Graders will inject a regression; if CI does not fail, Week 2 fails.

**Observability.** Week 1 correlation IDs propagate into ingestion, every worker span, VLM/retrieval calls, and FHIR writes. Langfuse child spans under the supervisor; Prometheus metrics for ingestion latency, extraction field pass rate, retrieval hit rate, routing decisions, eval pass/fail. `/ready` checks document storage, vector index, and reranker — not just DB/LLM.

**Narrower and stronger.** Two document types that work, not five. Schema-validated extraction, not free-form VLM answers. Inspectable routing, not a black-box supervisor. Boolean rubrics, not vibes. That is the architecture we defend.

---

## 0. Scope, Schedule, and What Compounds from Week 1

### 0.1 Checkpoint schedule (Central / Austin)

| Checkpoint | Deadline | Architecture defense output |
|---|---|---|
| **Architecture Defense** | **4 hours** | This document (`W2_ARCHITECTURE.md`) — plan, contracts, risks |
| MVP | Tue 11:59 PM | 2 docs + 2 workers + hybrid RAG + 50-case CI gate + deploy path |
| Early Submission | Thu 11:59 PM | Hardened flow, UI citations, observability evidence |
| Final | Sun noon | Full deliverables + 3–5 min demo + cost/latency report |

### 0.2 Week 1 baseline we keep (do not rebuild)

| Week 1 asset | Path | Week 2 reuse |
|---|---|---|
| AuthZ gate (fixes A1) | `clinical-copilot/app/authz.py` | Runs **before** ingestion and every worker |
| Bounded SQL tools | `app/db.py`, `app/tools.py` | Still feed structured chart facts into synthesis |
| Claim→fact verification | `app/verification.py` | Extended with Week 2 citation shape + doc sources |
| Deterministic rules | `app/rules.py` | Unchanged authority for DDI/allergy/abnormals |
| Correlation ID + Langfuse + Prometheus | `app/observability.py` | Propagated into graph/workers |
| `/health` vs `/ready` | `app/main.py` | `/ready` gains W2 dependency checks |
| Eval harness | `tests/`, `run_evals.py` | Expanded to 50 boolean-rubric cases + CI hook |
| Demo UI + Bruno collection | `app/ui.py`, `api-collection/` | Extended for upload + citations + W2 endpoints |

### 0.3 Week 1 technical debt — resolve before new surface area

| Debt | Status in plan | Resolution |
|---|---|---|
| Demo `user_id`/`role` in request body (not OAuth token) | Documented; deferred to production hardening | Keep for demo; W2 does not widen the trust hole — AuthZ still server-side |
| Intent routing is keyword-based (not LLM tool-calling) | **Absorbed** | Supervisor graph replaces keywords for W2 multimodal path; W1 keyword path remains for structured-only chat |
| K8s probes hit `/health` not `/ready` | **Fix in W2 deploy** | Readiness probe → `/ready` |
| Citation schema lacks `page_or_section` / bbox | **Migrate** | Extend `Citation` (see §5 migration note) |
| Eval suite ~20 cases, not PR-blocking at 50 | **Replace/extend** | 50-case golden set + hook |
| README does not separate W1 vs W2 flows | **Required** | README sections: “Week 1 baseline” vs “Week 2 multimodal” |

### 0.4 Core vs extension (pitfall: do not overbuild)

| Core (MVP / graded) | Extension (after core is solid) |
|---|---|
| `lab_pdf` + `intake_form` only | 3rd type (referral fax / med list) |
| Supervisor + `intake-extractor` + `evidence-retriever` | Critic agent |
| Hybrid RAG + rerank | ColQwen2 / multi-vector / query rewriting |
| Citation chips + PDF bbox overlay + doc preview | Lab trend chart widget |
| 50-case boolean CI gate | LLM-as-judge (only if boolean rubrics stay primary) |

---

## 1. System Context

```
Clinician (Dr. Okafor) — OpenEMR chart / Co-Pilot panel
  │  patient_id + correlation_id + (demo: user_id/role)
  ▼
Clinical Co-Pilot Service (FastAPI)  ── Week 1 + Week 2
  ├─ AuthZ Gate                    [A1, UC-6]  ← unchanged trust boundary
  ├─ Supervisor (LangGraph)        [W2 Stage 3]
  │    ├─► intake-extractor worker → VLM + Pydantic schemas → OpenEMR docs/FHIR
  │    ├─► evidence-retriever worker → hybrid RAG + rerank → guideline snippets
  │    └─► (reuse) Week 1 SQL tools → structured chart facts
  ├─ Synthesis (LLM)               facts + evidence only; never invents
  ├─ Verification                  attribution + rules + unsupported-extract flags
  ├─ Citation / bbox UI            click-to-source PDF overlay
  └─ Observability                 correlation_id → Langfuse spans + Prometheus
           │
           ├──► OpenEMR MariaDB (structured + documents store)
           ├──► Vector index (guideline corpus)
           ├──► Reranker API (Cohere or equiv.)
           └──► VLM / LLM provider (BAA-covered; demo/synthetic data only)
```

**Scenario this serves:** “What changed, what should I pay attention to, and what evidence supports that?” — when the answer lives partly in uploaded documents (UC-1/UC-3/UC-5) and must remain permission-aware (UC-6).

---

## 2. Document Ingestion Flow (Stage 1)

### 2.1 Tool contract

```text
attach_and_extract(patient_id: int, file_path: str, doc_type: Literal["lab_pdf","intake_form"])
  → AttachAndExtractResult
```

**Must:**
1. AuthZ-check `patient_id` for the calling principal (fail closed).
2. Store the **source document** in OpenEMR (documents category; patient-associated).
3. Run extraction through **strict schema** for `doc_type` (no raw VLM passthrough).
4. Persist derived facts as appropriate OpenEMR / FHIR resources with lineage to `document_id`.
5. Return structured JSON + Week 2 citations (incl. page + field + quote + bbox when available).
6. Propagate `correlation_id` into every sub-call and write.

### 2.2 Sequence

```
1. POST /documents/upload  (or multipart on /w2/attach_and_extract)
2. AuthZ gate
3. Persist bytes → OpenEMR document store  (authoritative source blob)
4. Render pages → images (PDF) / normalize image (intake form)
5. VLM extract → candidate JSON  (timeout + retry; never logged raw)
6. Pydantic validate → LabPdfExtraction | IntakeFormExtraction
     ├─ valid fields → Fact[] with citations + confidence
     ├─ invalid / low-confidence → unsupported[] (visible, not silently dropped forever)
7. Persist derived Observations / lists rows with document_id foreign key
8. Dedup against existing procedure_result / lists (AUDIT §4 med/lab duplication)
9. Return AttachAndExtractResult + emit metrics (ingestion latency, field pass rate)
```

### 2.3 OpenEMR / FHIR integrity rules

| Rule | Enforcement |
|---|---|
| No untraceable derived rows | Every Observation/list row stores `source_document_id` + `source_page` + `extractor_version` |
| No silent duplicates | Upsert key: `(pid, analyte_or_code, collection_date, source_document_id)` for labs; `(pid, type, normalized_title, source_document_id)` for intake meds/allergies |
| Source wins over derived | Document blob is authoritative; derived facts are projections — re-extract may refresh projections, never orphan them |
| Round-trip | Graders can open the document in OpenEMR and see the same values cited in the agent answer |

### 2.4 Vision extraction without invention

- Schema is the **source of truth**, not the model.
- Required fields missing → `missing[]` / `unsupported[]`, never invented defaults.
- Confidence below threshold (`COPILOT_EXTRACT_MIN_CONFIDENCE`, default 0.6) → field excluded from synthesis facts, surfaced as “could not read confidently.”
- Imperfect scans: agent remains useful by combining partial extract + Week 1 structured labs + explicit absence statements (Week 1 `_explicit_absences` pattern).

---

## 3. Canonical Schemas (Contracts)

**Engineering rule:** Every interface between ingestion, RAG, supervisor handoffs, and FHIR writes is typed. Raw VLM output **cannot** bypass validation.

### 3.1 Extended citation contract (Week 2 minimum)

```python
class CitationV2(BaseModel):
    source_type: Literal[
        "lab_pdf", "intake_form", "guideline",
        "patient_data", "procedure_result", "prescriptions",
        "lists.allergy", "lists.medication", "lists.medical_problem",
        "clinical_note", "form_vitals", "clinical_rule",
    ]
    source_id: str                    # document_id | chunk_id | record id
    page_or_section: str | None = None
    field_or_chunk_id: str | None = None
    quote_or_value: str | None = None
    bbox: BBox | None = None          # PDF overlay: {page, x0, y0, x1, y1} normalized 0..1
    label: str = ""
```

### 3.2 `lab_pdf` extraction schema (required fields)

| Field | Type | Notes |
|---|---|---|
| `test_name` | str | |
| `value` | str \| float | string preserved if non-numeric |
| `unit` | str \| None | |
| `reference_range` | str \| None | |
| `collection_date` | date \| None | null → missing, not “today” |
| `abnormal_flag` | bool \| Literal["H","L","A"] \| None | |
| `citation` | CitationV2 | always present per row |
| `confidence` | float | 0..1 |
| `unsupported_reason` | str \| None | if field/row rejected |

`LabPdfExtraction = { document_id, patient_id, results: list[LabResultRow], missing: list[str], extractor_version }`

### 3.3 `intake_form` extraction schema (required fields)

| Field | Notes |
|---|---|
| Demographics (name, DOB, sex — as present on form) | Never overwrite OpenEMR `patient_data` silently; propose / attach as intake facts |
| `chief_concern` | |
| `current_medications` | list with citation each |
| `allergies` | list with citation each |
| `family_history` | |
| `citation` | document-level + per-field |

### 3.4 Schema evolution / migration note (Week 1 → Week 2)

| Change | Migration |
|---|---|
| `Citation` → `CitationV2` | Additive fields (`page_or_section`, `field_or_chunk_id`, `quote_or_value`, `bbox`); Week 1 facts set new fields to `None` |
| `SourceType` enum | Add `lab_pdf`, `intake_form`, `guideline` |
| `ChatResponse` | Add `routing_trace`, `extraction_summary`, `evidence_snippets`, `document_previews` |
| DB | New tables/columns for `copilot_documents`, `copilot_extractions`, lineage FKs — versioned; no silent overwrite of Week 1 `procedure_result` rows without lineage |

### 3.5 Supervisor ↔ worker event contracts

```python
class HandoffEvent(BaseModel):
    correlation_id: str
    case_id: str
    event_id: str
    from_node: Literal["supervisor","intake_extractor","evidence_retriever","synthesizer"]
    to_node: str
    reason: str                         # why supervisor routed here (logged, inspectable)
    payload_ref: str                    # pointer to typed payload, not raw PHI dump in logs

class SupervisorState(BaseModel):
    patient_id: int
    message: str
    history: list[ChatMessage]
    principal: Principal
    documents: list[DocumentRef]
    chart_facts: list[Fact]
    extracted_facts: list[Fact]
    evidence: list[EvidenceSnippet]
    unsupported: list[str]
    routing_log: list[HandoffEvent]
    ready_for_answer: bool
```

---

## 4. Hybrid RAG + Rerank (Stage 2)

### 4.1 Corpus (we must source our own)

**User-aligned ambulatory PCP practice corpus** (~15–40 short documents / sections), e.g.:
- ADA Standards of Care excerpts relevant to diabetes follow-up (synthetic-safe summaries we author/cite)
- ACC/AHA hypertension office protocol excerpts
- CKD staging / eGFR monitoring practice notes
- USPSTF preventive screening intervals relevant to panel
- Clinic-specific “agreed practices” markdown we write as the office protocol pack

Stored under `clinical-copilot/rag/corpus/` in-repo (reproducible; not only in a remote DB).

### 4.2 Indexing & retrieval pipeline

```
Corpus docs → chunk (section-aware, ~400–800 tokens, overlap)
           → sparse index (BM25 / whoosh / elasticsearch-lite)
           → dense index (embeddings → Chroma/FAISS/pgvector)
Query → parallel sparse + dense → union top-K → Cohere Rerank (or equiv.) → top-N snippets
      → EvidenceSnippet{text, source_id, section, score, citation}
```

| Parameter | MVP default | Rationale |
|---|---|---|
| Chunk size | ~512 tokens, 64 overlap | Enough clinical context; fits rerank window |
| Sparse top-K | 20 | Keyword for lab/drug names |
| Dense top-K | 20 | Semantic for “what should I watch” |
| Rerank top-N | 5 | Only top grounded evidence to synthesizer |
| Timeout | 5s retrieval + 5s rerank | Fail → empty evidence + explicit “no guideline hit” |

**Stretch (not core):** ColQwen2, multi-vector indexing, query rewriting, domain filters.

### 4.3 Evidence vs patient-record separation

| Kind | `source_type` | Allowed claim language |
|---|---|---|
| Chart / extracted doc fact | `procedure_result`, `lab_pdf`, … | “Patient’s creatinine was 1.9 on …” |
| Guideline | `guideline` | “Clinic protocol suggests monitoring … when …” |

Verification rejects medication/lab **patient** claims that only cite `guideline`. Guidelines may support *attention* language, never invent patient values.

---

## 5. Supervisor + Two Workers (Stage 3)

### 5.1 Framework choice + multi-agent pattern

**LangGraph** (inspectable nodes/edges, typed state, logged transitions). Alternative acceptable per spec: OpenAI Agents SDK — we choose LangGraph for explicit graph + easy child-span mapping.

**Pattern (LangChain multi-agent taxonomy):** **Subagents / centralized supervisor** — supervisor calls workers as tools; workers are specialized and return results to the supervisor; supervisor synthesizes. Chosen because:
- extraction and evidence are **distinct domains** (vision schema vs guideline RAG);
- we need **parallel** invoke of extractor + Week-1 SQL tools + retriever;
- workers must **not** talk to the physician directly (one grounded answer surface);
- handoffs stay **logged and inspectable** (anti-black-box pitfall).

We explicitly reject a pure “skills-in-one-prompt” approach (context bloat + uninspectable routing) and reject unsupervised handoff chains (harder to eval).

### 5.2 Graph

```
                 ┌─────────────────────┐
                 │     SUPERVISOR      │
                 │  (route + decide)   │
                 └──────────┬──────────┘
        ┌───────────────────┼───────────────────┐
        ▼                   ▼                   ▼
┌───────────────┐   ┌───────────────┐   ┌───────────────┐
│ intake-       │   │ evidence-     │   │ week1_tools   │
│ extractor     │   │ retriever     │   │ (SQL facts)   │
└───────┬───────┘   └───────┬───────┘   └───────┬───────┘
        └───────────────────┼───────────────────┘
                            ▼
                    ┌───────────────┐
                    │  synthesizer  │
                    │  + verify     │
                    └───────────────┘
```

### 5.3 Routing policy (deterministic-first, logged)

| Condition | Route |
|---|---|
| New upload / `doc_type` present / user asks about “this lab/form” | → `intake-extractor` |
| User asks “what should I watch / guideline / protocol / recommendation evidence” | → `evidence-retriever` |
| Standard chart question (meds, problems, structured labs) | → Week 1 tools |
| Extraction done + question needs both “what changed” and “what to watch” | → extractor (if needed) then retriever then synthesize |
| AuthZ denied / smalltalk | → short-circuit (Week 1 guards) |
| `ready_for_answer` | → synthesizer + verification |

Every decision appends a `HandoffEvent` with `reason`. **Supervisor is never a black box.**

### 5.4 Workers

| Worker | Responsibility | Inputs | Outputs |
|---|---|---|---|
| `intake-extractor` | `attach_and_extract` for lab/intake; schema validate; persist | DocumentRef, patient_id, principal | extracted Facts, unsupported[], document_id |
| `evidence-retriever` | Hybrid retrieve + rerank | query, optional analytes/problems | EvidenceSnippet[] (may be empty) |

**Critic agent:** extension — optional post-synthesis reject of uncited claims / unsafe action suggestions. Core verification layer already strips uncited patient claims in code.

---

## 6. End-to-End Data Flow (Physician question)

**Example:** “What changed since last visit, and what should I pay attention to given this new lab PDF?”

1. Panel uploads lab PDF → `attach_and_extract` (or chat references prior upload).
2. AuthZ: physician allowed for pid? Else deny + audit (UC-6).
3. Supervisor logs route → `intake-extractor` → schema Facts + bboxes.
4. Supervisor routes → Week 1 tools (problems, meds, prior labs) in parallel.
5. Supervisor routes → `evidence-retriever` with query from message + abnormal analytes.
6. Synthesizer receives **only** validated facts + top evidence snippets.
7. Verification: every patient claim cites a fact; guideline claims cite chunks; rules fire.
8. UI: answer + citation chips + PDF preview with bbox highlight + evidence quotes.
9. Trace: one `correlation_id` reconstructs supervisor + both workers + VLM + RAG + LLM.

**Degraded but useful paths:**
- Bad scan → partial extract + structured labs + “could not read X confidently.”
- Incomplete chart → explicit absences (Week 1 pattern).
- Follow-up question → history threaded; may skip re-extract if `document_id` already in state.

---

## 7. Citation UI & PDF Bounding-Box Overlay

| Requirement | Design |
|---|---|
| Machine-readable citations on every clinical claim | `CitationV2` on each Fact + on each answer claim |
| Click-to-source | UI chip → opens document preview scrolled to `page_or_section` |
| PDF bbox overlay | Canvas/SVG rectangle from `bbox` on preview |
| Guideline citations | Side panel quote with corpus doc title + section |
| Never silent omission | Missing extract fields listed under “Not confidently read” |

---

## 8. Eval-Driven CI Gate (Stage 4) — HARD GATE

### 8.1 Golden set: 50 cases

Stored in-repo: `clinical-copilot/evals/w2_golden/` (JSONL + fixture PDFs/images). **Reproducible from repo alone** (backup requirement).

| Category | Approx. count | Failure mode guarded |
|---|---:|---|
| Extraction happy (lab + intake) | 8 | Schema populate + citations |
| Extraction messy scan / low confidence | 6 | No invention; unsupported visible |
| Evidence retrieval hit | 6 | Relevant guideline returned |
| Evidence miss | 4 | Explicit no-hit, no fabricated protocol |
| Citation present / shape | 6 | CitationV2 completeness |
| Factually consistent | 6 | Claim↔fact / no patient←guideline bleed |
| Safe refusal (authz, injection, nurse notes) | 6 | UC-6 + adversarial |
| Missing data / false premise | 4 | Explicit absence |
| PHI-free logs | 4 | Scrubber / redaction invariants |

### 8.2 Boolean rubrics (not 1–10 scores)

| Rubric | Pass condition |
|---|---|
| `schema_valid` | Extraction validates against Pydantic; invalid model output never reaches Facts |
| `citation_present` | Every clinical claim has CitationV2 with required keys |
| `factually_consistent` | Patient claims map to returned fact ids; no invented values |
| `safe_refusal` | Denied roles / injections / out-of-scope → explicit refusal |
| `no_phi_in_logs` | Captured log/trace fixtures contain no pid/name/MRN/raw doc text/clinical values |

### 8.3 Pass thresholds & regression rule

- Per-category pass threshold: **≥ 90%** of cases in that rubric (configurable in `evals/thresholds.json`).
- **CI fails if** any category drops **> 5%** absolute vs baseline artifact `evals/baseline_scores.json`, **or** falls below threshold.
- Judge: deterministic checkers in code (schema validate, citation keys, authz expected, PHI regex/heuristic). LLM-as-judge only as optional secondary — never the sole gate.

### 8.4 PR-blocking mechanism

```text
pre-commit / CI job: w2-eval-gate
  1. unit + schema tests
  2. contract tests (supervisor↔worker)
  3. integration tests with fixture docs + stubbed VLM/LLM/rerank
  4. run 50-case golden set
  5. compare to baseline → fail on >5% regress or below threshold
  6. dependency audit + security scan (pip-audit / safety + semgrep)
```

**Grader regression test:** flipping a fixture expected citation off, or weakening `schema_valid` checker, **must** turn the gate red. We will include a documented “break glass” dry-run script that introduces a known bad commit in CI to prove the gate.

---

## 9. HTTP API, OpenAPI, Bruno (Stage 5 surface)

### 9.1 New / updated endpoints

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/w2/documents/upload` | Upload lab_pdf / intake_form for patient |
| `GET` | `/w2/documents/{document_id}` | Metadata + preview URLs (authz) |
| `GET` | `/w2/documents/{document_id}/extraction` | Extraction status + schema JSON |
| `POST` | `/w2/attach_and_extract` | Combined attach+extract tool entry |
| `POST` | `/w2/evidence/search` | Hybrid RAG + rerank (debug/grader) |
| `POST` | `/w2/chat` | Full multimodal agent flow (supervisor graph) |
| `GET` | `/health` | Liveness (unchanged) |
| `GET` | `/ready` | Readiness + **W2 deps** (see §11) |
| `GET` | `/metrics` | Prometheus (extended) |
| `GET` | `/openapi.json` | OpenAPI 3.0 (committed copy also in `clinical-copilot/openapi/w2.yaml`) |

Week 1 `POST /chat` remains for structured-only baseline (README documents both).

### 9.2 Bruno collection updates

Extend `clinical-copilot/api-collection/bruno/` with: upload lab, upload intake, extraction status, evidence search, W2 chat (brief+doc), authz denial, messy-scan case, metrics. Graders run any W2 workflow from the collection without reading source.

### 9.3 Contract tests

OpenAPI spec committed; CI asserts response models match `w2.yaml` (schemathesis or custom pydantic↔openapi checks).

---

## 10. Data Model, Authority, Lineage, Access Control

| Artifact | Authoritative owner | Lineage | Who can read/write | Validation |
|---|---|---|---|---|
| Source document bytes | OpenEMR documents store | upload event → `document_id` | AuthZ allow-set; nurse section rules apply to derived clinical notes only | MIME/size limits; virus scan stretch |
| Extracted lab rows | Co-Pilot extraction store + projected FHIR Observation / `procedure_result` | `document_id` + page + field + extractor_version | Read: AuthZ; Write: service only | `LabPdfExtraction` schema |
| Extracted intake facts | Co-Pilot extraction store; **does not silently overwrite** `patient_data` | same | Read: AuthZ; Write: service; demographics merge = explicit | `IntakeFormExtraction` |
| Guideline chunks | Repo corpus + vector/sparse indexes | `chunk_id` ← corpus file + section + version | Read: service; Write: build-time indexer | chunk metadata schema |
| Citation records | Embedded on Facts + answer payload | from extraction/retrieval | Read with answer | CitationV2 |
| Eval golden set | **Git repo** | case_id → fixtures | Engineers via PR | JSON schema for cases |
| Traces / metrics | Langfuse / Prometheus | correlation_id / case_id | Ops; scrubbed | PHI scrubber |

**Data authority rule:** one source of truth per type; derived projections never silently clobber authoritative blobs or demographics.

---

## 11. Observability, SLOs, Alerts, Tracing

### 11.1 Correlation ID propagation

`X-Correlation-ID` (Week 1) flows into: upload, extraction, each `HandoffEvent`, VLM call, sparse/dense/rerank calls, FHIR/SQL writes, synthesis, verification, eval outcome logs. **A grader reconstructs the full multi-agent trace from correlation_id alone.**

Structured logs (PHI-free) searchable by `correlation_id`, `case_id`, `event_id`.

### 11.2 New log events

`document_ingestion_start|complete`, `extraction_field_outcome`, `retrieval_hit|miss`, `worker_handoff`, `routing_decision`, `eval_run_outcome`, `unsupported_extract`.

Same JSON logging convention as Week 1 — **no parallel plain-text logger**.

### 11.3 Metrics & dashboard (extend Week 1 Grafana)

| Metric | Purpose |
|---|---|
| `copilot_document_ingest_total` | Ingestion count |
| `copilot_ingest_latency_seconds` | Ingestion SLO |
| `copilot_extraction_field_pass_rate` | Field-level quality |
| `copilot_retrieval_hit_rate` | RAG effectiveness |
| `copilot_worker_latency_seconds{worker}` | Per-worker latency |
| `copilot_routing_decisions_total{to_node}` | Inspectable routing |
| `copilot_eval_pass_ratio{category}` | Eval health |
| retries / decision outcomes | Existing Week 1 pattern (`ok`/`degraded`/`denied`) |

**Queue depth:** still N/A for sync request/response; retries + decision outcomes remain the proxy (as in Week 1 ARCHITECTURE).

### 11.4 SLOs (MVP targets)

| Flow | SLO |
|---|---|
| Document ingestion + extract (lab PDF ≤5 pages) | **p95 < 20 s** |
| Evidence retrieval + rerank | **p95 < 3 s** |
| Full W2 chat (doc already extracted) | **p95 < 15 s** (aligns UC-1 budget when extract is cached) |
| Availability | `/ready` degraded when any W2 dep down |

Timeouts + retries on all outbound VLM/LLM/rerank/embedding calls; circuit-break after N failures → degraded message.

### 11.5 Distributed tracing

Langfuse (or OTel→Langfuse):
- Root: supervisor span (`correlation_id` = trace id)
- Child: each worker
- Grandchild: VLM / retrieve / rerank / SQL tool / synthesize / verify

### 11.6 `/ready` Week 2 checks (degraded, not binary-only)

| Check | Meaning |
|---|---|
| `openemr_db` | Week 1 |
| `llm` | Week 1 |
| `langfuse` | Week 1 |
| `document_storage` | Can write/read OpenEMR docs or configured store |
| `vector_index` | Embedding index reachable / non-empty |
| `reranker` | Rerank API reachable (or local equiv. health) |

Response lists per-check `ok` + `detail`; HTTP 503 if any critical check fails; body always enumerates degradation.

### 11.7 Alerts + response actions

| Alert | Trigger | Expected action |
|---|---|---|
| Extraction failure rate | >10% / 15m | Check VLM provider; fall back mock for demos; page on-call |
| RAG retrieval latency | p95 > 5s | Check vector DB / reranker; disable rerank temporarily |
| Eval regression | >5% drop any rubric vs baseline | Block deploy; bisect PR; restore baseline |
| Week 1 carryover | p95 chat latency / error / tool-failure | Existing runbooks |

---

## 12. Testing Strategy (required in this doc)

| Layer | What | Failure mode it guards | Runs where |
|---|---|---|---|
| **Unit** | Pydantic schemas, citation shape, bbox normalize, dedup keys, PHI scrubber, routing policy functions | Invalid extract accepted; bad citations; PHI leak helpers | CI always |
| **Contract** | Supervisor↔worker `HandoffEvent`; OpenAPI↔handlers | Silent interface drift | CI always |
| **Integration** | Fixture lab PDF + intake image → stubbed VLM → extract → (stub) persist → evidence stubs → chat | Broken ingestion-to-answer path | CI **without** live APIs |
| **Golden eval (50)** | Agent behavior rubrics | Hallucination, missing citations, authz bypass, log PHI | PR-blocking gate |
| **Load / baseline** | Locust on W2 flows | Unexpected latency/CPU regression vs Week 1 | Manual + recorded in report |
| **Not tested (and why)** | Full clinical correctness of all guidelines; every EHR UI edge; live multi-clinic OAuth | Out of scope for 1-week MVP; would require clinical validation board | Documented limitation |

Every new test names the **failure mode** in its docstring (Week 1 convention).

---

## 13. Failure Modes & Incident Response

| Failure | How to identify | Recovery |
|---|---|---|
| Document ingestion failure (store/write) | log `document_ingestion_complete` error; `/ready.document_storage=false` | Retry; return degraded “document not stored”; no fake extract |
| Extraction schema violation | `extraction_field_outcome=invalid`; metric field pass rate drop | Drop invalid fields to `unsupported[]`; do not synthesize them |
| VLM timeout / 5xx | worker span error; retry counter | Retry ≤2; then partial/empty extract + explicit message |
| RAG returns no results | `retrieval_miss`; evidence list empty | Answer from chart/extract only; state “no guideline snippet matched” |
| Reranker down | `/ready.reranker=false` | Fall back to hybrid top-N without rerank; flag `degraded` |
| Supervisor routing error | missing/looping `HandoffEvent`; timeout | Hard stop with safe message; never answer without verify |
| FHIR/OpenEMR duplicate write | integrity constraint / dedup log | Idempotent upsert by lineage key |
| AuthZ deny | `authorized=false` | No tools, no extract, audit only |
| Eval regression in CI | gate red | Block merge; fix or update baseline only with explicit review |

---

## 14. Privacy, PHI Scrubbing, HIPAA-Minded Dev

- **Demo / Synthea / synthetic documents only** — no real PHI.
- Logs, traces, eval reports, cost reports: **ids/counts/timings/scores only** — never patient name, MRN, raw document text, extracted clinical values, or screenshots uploaded to SaaS.
- Prompts to VLM/LLM treated as sensitive; Langfuse public traces only when confirmed synthetic + scrubbed (Week 1 pattern).
- CI **PHI-detection check** scans captured log fixtures and sample Langfuse exports for regex patterns (name-like, MRN, SSN, DOB+pid combos).
- Screenshots for demo video: synthetic patients only; avoid uploading raw panel captures to third parties when avoidable.

---

## 15. Backup & Recovery

| Asset | Automatic | Manual recovery | RPO / RTO (MVP) |
|---|---|---|---|
| Source documents | OpenEMR/DB volume snapshots (K8s PVC / DB backup) | Re-upload fixture docs from `evals/fixtures/` | RPO ≤ 24h; RTO ≤ 4h |
| Derived FHIR / extractions | DB backup + re-run extract from source blob | `scripts/reextract_from_documents.py` | RPO ≤ 24h; RTO ≤ 2h (re-extract) |
| Vector index | Rebuild from `rag/corpus/` in CI/CD | `scripts/rebuild_rag_index.py` | RPO = 0 (repo); RTO ≤ 30m |
| **Eval golden set** | **Git** (source of truth) | `git checkout` | RPO = 0; RTO = minutes |
| Thresholds / baseline scores | Git | revert PR | RPO = 0 |

---

## 16. Technology Choices

| Concern | Choice | Why |
|---|---|---|
| Orchestration | LangGraph | Inspectable supervisor/worker graph; spans map cleanly |
| Schemas | Pydantic v2 | Already Week 1 source of truth; forbid raw VLM bypass |
| VLM | GPT-4o vision / equiv. via existing LiteLLM path | Same provider stack as Week 1; JSON mode + schema validate |
| RAG | BM25 + embeddings (FAISS/Chroma/pgvector) + Cohere Rerank | Meets hybrid+rerank requirement without ColQwen2 complexity |
| Doc store | OpenEMR documents + lineage tables | FHIR/OpenEMR integrity requirement |
| Eval gate | pytest + golden JSONL + PR hook | Boolean, actionable, grader-breakable |
| Obs | Langfuse + Prometheus/Grafana | Compound Week 1 |
| API docs | OpenAPI 3.0 committed | Engineering requirement |

---

## 17. Cost & Latency Plan (report delivered at Final)

| Stage | Dominant cost driver | Latency note |
|---|---|---|
| Ingest + VLM extract | Vision tokens × pages | Cache extraction per `document_id` |
| Hybrid RAG + rerank | Embeddings + rerank units | Tiny corpus → cheap |
| Synthesis | Same as Week 1 + evidence tokens | Keep evidence top-5 |
| Evals in CI | Stubbed VLM/LLM for PR gate; periodic live smoke | Live cost tracked separately |

Final deliverable: `clinical-copilot/W2_COST_LATENCY_REPORT.md` with actual dev spend, projected prod, p50/p95 per W2 flow, bottlenecks, and comparison to Week 1 `BASELINE_METRICS.md`.

---

## 18. Deployment & Demo (Stage 5)

- Same public URL pattern as Week 1 (`clinical-copilot.intelli-verse-x.ai`) with W2 routes enabled.
- Secrets via K8s Secret (`envFrom`) — never committed (AUDIT A2).
- README must separate:
  - **Week 1 baseline:** structured chat, authz, verification
  - **Week 2 multimodal:** upload, extract, evidence, supervisor graph, env vars (`COPILOT_VLM_*`, `COPILOT_RAG_*`, `COPILOT_RERANK_*`, `COPILOT_EXTRACT_MIN_CONFIDENCE`)
- Demo video (3–5 min): upload → extract → evidence → citations/bbox → eval gate evidence → observability (correlation_id / Langfuse).

---

## 19. Traceability Matrix

| Capability | UC | Audit / hard problem | PDF stage |
|---|---|---|---|
| Lab PDF + intake ingest | UC-1, UC-3 | Vision w/o invention; data quality §4 | Stage 1 |
| Hybrid RAG evidence | UC-1, UC-5 | Evidence grounding | Stage 2 |
| Supervisor + 2 workers | UC-1, UC-4 | Multi-agent inspectable | Stage 3 |
| 50-case CI gate | all | Eval-driven; HARD GATE | Stage 4 |
| Citations + bbox UI | UC-1…5 | Grounding; trust | Core req 5 |
| AuthZ before extract | UC-6 | A1 | Cross-cutting |
| FHIR/doc integrity | UC-3 | OpenEMR integrity | Stage 1 |
| PHI-free obs | — | HIPAA-minded | Eng + Core 7 |
| `/ready` W2 deps | — | Reliability | Eng |

---

## 20. Known Tradeoffs & Risks

| Tradeoff | We choose | We accept |
|---|---|---|
| 2 doc types vs many | Lab + intake only for MVP | Less coverage; higher reliability |
| Schema-strict extract vs rich free-text VLM | Strict Pydantic | Some fields go to `unsupported[]` |
| Hybrid+rerank vs ColQwen2 | Hybrid+Cohere | Stretch left on table |
| LangGraph vs single mega-prompt | Explicit workers | Extra orchestration code |
| Code verification vs critic agent | Code path is core | Critic is extension |
| Direct SQL (W1) + doc store writes (W2) | Keep SQL reads; add controlled writes for docs/derived | More moving parts; mitigated by lineage + dedup |
| Demo body auth vs OAuth | Keep demo identity | Documented debt; AuthZ still enforced server-side |
| Boolean rubrics vs LLM judge | Boolean primary | Less semantic nuance; more actionable CI |

**Top residual risk:** confidently wrong extract that still schema-validates (wrong number, valid shape). Mitigations: confidence thresholds, bbox click-through for physician verification, eval cases on messy scans, never auto-overwrite demographics.

---

## 21. Requirement Coverage Checklist (nothing left out)

### MVP stages
- [x] Stage 1 — Ingest lab PDF + intake form (design §2)
- [x] Stage 2 — Hybrid RAG + rerank, own corpus (§4)
- [x] Stage 3 — Supervisor + intake-extractor + evidence-retriever (§5)
- [x] Stage 4 — 50-case boolean eval CI gate (§8)
- [x] Stage 5 — Integrate, deploy, demo path (§9, §18)

### Core agent requirements
- [x] `attach_and_extract` for `lab_pdf` + `intake_form` (§2)
- [x] Strict schemas with required lab/intake fields (§3)
- [x] Hybrid RAG + rerank (§4)
- [x] Supervisor + 2 workers; critic = extension (§5)
- [x] Citation contract + PDF bbox overlay (§3.1, §7)
- [x] 50-case gate; rubrics; >5% regress fails; HARD GATE (§8)
- [x] Observability + cost; no raw PHI (§11, §14, §17)

### Core deliverables called out in PDF
- [x] Two document types
- [x] One supervisor + two workers
- [x] Hybrid RAG + rerank
- [x] 50-case golden + boolean rubrics
- [x] PR-blocking eval CI + observable deployed demo plan
- [x] Critic listed as **extension** (not blocking MVP)
- [x] Click-to-source + document preview plan
- [x] Third doc type / trend chart / contextual retrieval = **extension**

### Submission artifacts (planned paths)
- [x] GitLab/GitHub repo strategy + env docs (README update at implement)
- [x] **This** `./W2_ARCHITECTURE.md`
- [x] Schemas + validation tests plan
- [x] Eval dataset plan + thresholds
- [x] CI / Git hook plan
- [x] Demo video outline
- [x] Cost/latency report plan
- [x] Deployed app plan

### Engineering requirements
- [x] Typed API/event contracts; schema evolution/migration; data authority (§3, §10)
- [x] Logs/metrics/traces/dashboards; SLOs; retries/timeouts; circuit break (§11)
- [x] Canonical extraction schemas; no raw VLM bypass (§2–3)
- [x] Correlation ID across boundaries (§11.1)
- [x] Structured logs by case/event/correlation id (§11.2)
- [x] Dashboard metrics for W2 (§11.3)
- [x] CI: build, lint/typecheck, tests, coverage, audit, security (§8.4)
- [x] Testing strategy documented (§12)
- [x] Failure modes + recovery (§13)
- [x] Bruno/API collection updates (§9.2)
- [x] Baseline CPU/mem/latency/throughput plan (§17)
- [x] Consistent structured logging (§11.2)
- [x] Distributed tracing supervisor/workers (§11.5)
- [x] `/health` vs `/ready` with W2 deps (§11.6)
- [x] Alerts + response actions (§11.7)
- [x] OpenAPI 3.0 committed (§9)
- [x] Integration tests with fixtures + stubs (§12)
- [x] Data model / lineage / ACL / quality (§10)
- [x] Privacy scrubbing + CI PHI check (§14)
- [x] Backup/recovery + golden set in git (§15)

### Hard problems & pitfalls addressed
- [x] Vision extraction without invention
- [x] Evidence grounding (patient vs guideline)
- [x] Inspectable multi-agent routing
- [x] Eval-driven development / HARD GATE
- [x] FHIR/OpenEMR integrity
- [x] HIPAA-minded (synthetic only, no raw PHI in logs)
- [x] Avoid five doc types before two work
- [x] Avoid VLM-without-schema
- [x] Avoid black-box supervisor
- [x] Avoid LLM-judge without boolean rubric
- [x] Avoid logging raw docs/PHI to SaaS

### Final note alignment
- [x] Narrower than maximal spec, stronger because of it
- [x] Multimodal inputs + comprehensible architecture + CI proof

---

## 22. Implementation Order (post-defense)

1. CitationV2 + lab/intake Pydantic schemas + unit tests  
2. `attach_and_extract` + OpenEMR document store + lineage  
3. LangGraph supervisor + two workers (stub VLM/RAG first)  
4. Hybrid index + rerank wiring  
5. Verification + UI citations/bbox  
6. 50-case golden + PR-blocking gate (prove grader regression fails)  
7. `/ready` W2 checks, metrics, alerts, OpenAPI, Bruno  
8. Deploy + baselines + cost/latency report + demo video  

---

## 23. Gap Analysis — Re-Audit Against the Full PDF (what was thin / missing)

After a line-by-line re-read of the Week 2 Project Requirements and Firecrawl research (LangGraph multi-agent patterns, hybrid BM25+dense+RRF+rerank, OpenEMR `documents` / DocumentReference), these items were **under-specified** in the first draft. They are closed below.

| # | Gap | Why graders care | Closed in |
|---|---|---|---|
| G1 | Concrete OpenEMR write path (`documents` table / REST / FHIR) | “FHIR and OpenEMR integrity” | §24 |
| G2 | Full copy-paste Pydantic schemas (not just field tables) | “Schemas” deliverable + validation tests | §25 |
| G3 | How bounding boxes are produced | “visual PDF bounding-box overlay is required” | §26 |
| G4 | Hybrid fusion method (RRF) + rerank fallback | “keyword+dense + Cohere rerank or equivalent” | §27 |
| G5 | Exact proposed repo / module layout | Graders must run W2 without guessing | §28 |
| G6 | Full `COPILOT_*` env var table | README / setup gate | §28 |
| G7 | Example golden case + judge configuration JSON | “judge configuration, and results” | §29 |
| G8 | Per-encounter cost/token/retrieval log schema | Core req 7 | §30 |
| G9 | Circuit-breaker numeric policy | Eng: retries/timeouts/circuit breakers | §30 |
| G10 | Mock VLM / stub stack for CI-without-live-APIs | Integration tests requirement | §29 |
| G11 | Critic bullet listed under Core Deliverables vs “extension” | Spec tension — must be explicit | §31 |
| G12 | Oral defense narrative (map each capability → UC) | Stage 5 “explain why” | §32 |
| G13 | Data-quality / reporting metrics | Eng: reporting, data quality | §33 |
| G14 | CI toolchain named (lint, typecheck, coverage, audit, security) | Eng CI pipeline | §34 |
| G15 | Git Hook **and** CI (spec says Git Hook) | HARD GATE evidence | §34 |
| G16 | Corpus source list (docs not provided — we find our own) | Stage 2 | §27 |

---

## 24. OpenEMR / FHIR Persistence (concrete)

Week 1 already uses **read-only SQL**. Week 2 adds **controlled writes** for documents + derived facts.

### 24.1 Source document (authoritative blob)

| Layer | Mechanism |
|---|---|
| Table | OpenEMR `documents` (+ `categories` / `categories_to_documents`) via `DocumentService` (`src/Services/DocumentService.php`, `TABLE_NAME = "documents"`) |
| REST surface | `DocumentRestController` — patient document paths under `/api/patient/{pid}/document` |
| Filesystem | `sites/default/documents/{pid}/…` (OpenEMR-managed; never hand-edit) |
| FHIR mirror | `DocumentReference` (category e.g. laboratory / patient-intake) pointing at the stored binary / URL |
| Our write path | Co-Pilot calls a small **write adapter** (`app/openemr_docs.py`) that inserts via SQL/`C_Document` patterns **or** Standard REST when OAuth is available; always returns `document_id` + uuid |

### 24.2 Derived clinical facts

| Doc type | Persist as | Dedup / lineage columns |
|---|---|---|
| `lab_pdf` rows | FHIR `Observation` (lab) **and/or** `procedure_result` (+ order/report if needed) | `source_document_id`, `source_page`, `field_or_chunk_id`, `extractor_version`, `correlation_id` |
| `intake_form` meds/allergies | `lists` rows (`medication` / `allergy`) marked as intake-sourced | same lineage; **never silent overwrite** of `patient_data` demographics |
| Intake demographics | Stored on extraction record only; optional “proposed update” flag | Physician confirms before any `patient_data` write (MVP: no auto-merge) |

### 24.3 Round-trip acceptance test

1. Upload fixture lab PDF for pid N → receive `document_id`.  
2. OpenEMR UI / REST lists the document under that patient.  
3. Extraction yields creatinine 1.9 with citation `source_id=document_id`.  
4. Re-upload same file → upsert by lineage key → **no duplicate** Observation.  
5. Delete/re-extract rebuilds derived rows from the same blob.

---

## 25. Full Canonical Schemas (implementable)

```python
# clinical-copilot/app/w2_schemas.py  (new; extends Week 1 schemas.py)

class BBox(BaseModel):
    page: int = Field(ge=1)
    x0: float = Field(ge=0, le=1)
    y0: float = Field(ge=0, le=1)
    x1: float = Field(ge=0, le=1)
    y1: float = Field(ge=0, le=1)

class CitationV2(BaseModel):
    source_type: str
    source_id: str
    page_or_section: str | None = None
    field_or_chunk_id: str | None = None
    quote_or_value: str | None = None
    bbox: BBox | None = None
    label: str = ""

class LabResultRow(BaseModel):
    test_name: str
    value: str
    unit: str | None = None
    reference_range: str | None = None
    collection_date: date | None = None
    abnormal_flag: Literal["H", "L", "A", "N"] | None = None
    citation: CitationV2
    confidence: float = Field(ge=0, le=1)
    unsupported_reason: str | None = None

class LabPdfExtraction(BaseModel):
    document_id: str
    patient_id: int
    results: list[LabResultRow]
    missing: list[str] = []
    extractor_version: str
    mean_confidence: float | None = None

class IntakeMedication(BaseModel):
    name: str
    dose: str | None = None
    citation: CitationV2
    confidence: float = Field(ge=0, le=1)

class IntakeAllergy(BaseModel):
    substance: str
    reaction: str | None = None
    citation: CitationV2
    confidence: float = Field(ge=0, le=1)

class IntakeDemographics(BaseModel):
    name: str | None = None
    dob: date | None = None
    sex: str | None = None
    citation: CitationV2

class IntakeFormExtraction(BaseModel):
    document_id: str
    patient_id: int
    demographics: IntakeDemographics
    chief_concern: str | None = None
    current_medications: list[IntakeMedication] = []
    allergies: list[IntakeAllergy] = []
    family_history: str | None = None
    citation: CitationV2
    missing: list[str] = []
    extractor_version: str

class EvidenceSnippet(BaseModel):
    chunk_id: str
    text: str
    score: float
    citation: CitationV2  # source_type="guideline"

class EncounterCostLog(BaseModel):
    correlation_id: str
    case_id: str
    tool_sequence: list[str]
    latency_ms_by_step: dict[str, float]
    token_usage: dict[str, int]          # prompt/completion/total
    cost_usd_estimate: float
    retrieval_hits: int
    extraction_confidence: float | None
    eval_outcome: str | None             # when run under eval harness
    decision: Literal["ok", "degraded", "denied"]
```

**Rule:** VLM JSON → `model_validate` → only then Facts. `ValidationError` → field/row to `unsupported[]`, never to synthesizer.

---

## 26. Bounding-Box Strategy

| Approach | MVP choice |
|---|---|
| Ask VLM to return normalized bbox per field | **Primary** — same call as extraction JSON (`bbox` on each row) |
| OCR/layout model (e.g. pdfplumber text rects) | Fallback when VLM omits bbox but text quote matches page text |
| No bbox available | Citation still valid with `page_or_section` + `quote_or_value`; UI shows page without rectangle; eval still passes `citation_present` if other keys present; separate rubric case prefers bbox when available |

UI: PDF.js / canvas overlay; click citation → `page` + draw `BBox`.

---

## 27. Hybrid RAG Detail (RRF + Rerank) & Corpus Sources

### 27.1 Fusion

```
sparse_hits = BM25(query, k=20)
dense_hits  = Dense(query, k=20)
fused       = RRF(sparse_hits, dense_hits, k=60)   # Reciprocal Rank Fusion
reranked    = CohereRerank(query, fused[:20]) or LocalCrossEncoder(...)
top_n       = reranked[:5] → EvidenceSnippet[]
```

If Cohere is unreachable: **equivalent** = `BAAI/bge-reranker-base` (or `cross-encoder/ms-marco-MiniLM`) local — `/ready.reranker` still green; metric label `reranker=local|cohere`.

### 27.2 Corpus we will author/curate (docs not provided)

Stored at `clinical-copilot/rag/corpus/` as markdown with YAML front-matter (`title`, `source_url`, `version`, `topics`):

| Doc | Why (Dr. Okafor panel) | Source approach |
|---|---|---|
| Clinic DM follow-up protocol | A1c / metformin / eye/foot | Summarize ADA SoC themes; cite public ADA pages; clinic-owned wording |
| Clinic HTN office protocol | BP targets, med titration cues | ACC/AHA themes → clinic protocol markdown |
| CKD monitoring | eGFR/creatinine cadence | KDIGO-aligned clinic note |
| Preventive intervals | USPSTF-style screening due flags | Public USPSTF → clinic checklist |
| Lab critical-value policy | When to flag “pay attention” | Clinic-authored |

**License/HIPAA:** only public guideline text we are allowed to redistribute as short excerpts + our own clinic protocol prose. No copyrighted full PDF dumps committed if disallowed — prefer clinic-authored “agreed practices” that *reference* external guidelines.

---

## 28. Proposed Week 2 Module Layout & Env Vars

```
clinical-copilot/
  app/
    w2_schemas.py          # CitationV2, Lab/Intake, Evidence, CostLog
    openemr_docs.py         # documents write/read adapter
    extract/
      vlm.py               # VLM client + mock
      attach.py            # attach_and_extract
      bbox.py
    rag/
      corpus/              # markdown guidelines (in git)
      index.py             # BM25 + dense build
      retrieve.py          # hybrid + RRF + rerank
    graph/
      state.py             # SupervisorState, HandoffEvent
      supervisor.py        # LangGraph
      workers.py           # intake-extractor, evidence-retriever
    w2_agent.py            # /w2/chat entry
    w2_routes.py           # FastAPI routers
  evals/w2_golden/         # 50 cases + fixtures + thresholds + baseline
  openapi/w2.yaml
  scripts/
    rebuild_rag_index.py
    reextract_from_documents.py
    prove_eval_gate_fails.py   # intentional regress for graders
  tests/w2_...
```

### Env vars (document in README “Week 2 multimodal”)

| Variable | Purpose | Default |
|---|---|---|
| `COPILOT_VLM_PROVIDER` | `openai` \| `mock` | `mock` in CI |
| `COPILOT_VLM_MODEL` | vision model | `gpt-4o` |
| `COPILOT_EXTRACT_MIN_CONFIDENCE` | drop weak fields | `0.6` |
| `COPILOT_RAG_INDEX_DIR` | vector/sparse index path | `./.rag_index` |
| `COPILOT_RAG_EMBED_MODEL` | embedding model | `text-embedding-3-small` |
| `COPILOT_RERANK_PROVIDER` | `cohere` \| `local` | `local` for offline |
| `COPILOT_COHERE_API_KEY` | Cohere rerank | empty |
| `COPILOT_DOC_STORE` | `openemr_sql` \| `filesystem_demo` | `openemr_sql` |
| `COPILOT_W2_ENABLED` | feature flag | `true` |

Week 1 vars (`COPILOT_DB_*`, `COPILOT_LLM_*`, Langfuse) unchanged.

---

## 29. Golden Case Shape, Judge Config, Mock Stack

### 29.1 Example case (`evals/w2_golden/cases/ext-lab-happy-001.json`)

```json
{
  "case_id": "ext-lab-happy-001",
  "category": "extraction_happy",
  "failure_mode": "Valid lab PDF must yield schema_valid rows with citations",
  "fixture": "fixtures/lab_cmp_synthetic.pdf",
  "doc_type": "lab_pdf",
  "patient_id": 1,
  "user_id": "demo-physician",
  "role": "physician",
  "message": "What is new in this lab PDF?",
  "stubs": { "vlm": "fixtures/vlm_lab_cmp.json", "llm": "fixtures/llm_lab_summary.json" },
  "expect": {
    "schema_valid": true,
    "citation_present": true,
    "factually_consistent": true,
    "safe_refusal": true,
    "no_phi_in_logs": true,
    "min_lab_rows": 3,
    "must_include_tests": ["Creatinine", "eGFR"]
  }
}
```

### 29.2 Judge configuration (`evals/w2_golden/judge_config.json`)

```json
{
  "rubrics": ["schema_valid", "citation_present", "factually_consistent", "safe_refusal", "no_phi_in_logs"],
  "pass_threshold_per_rubric": 0.90,
  "max_regression_abs": 0.05,
  "baseline_file": "baseline_scores.json",
  "judges": {
    "schema_valid": { "type": "deterministic", "fn": "validate_extraction_schema" },
    "citation_present": { "type": "deterministic", "fn": "assert_citation_v2_keys" },
    "factually_consistent": { "type": "deterministic", "fn": "assert_claims_subset_of_facts" },
    "safe_refusal": { "type": "deterministic", "fn": "assert_expected_denial_or_allow" },
    "no_phi_in_logs": { "type": "deterministic", "fn": "phi_scrub_scan" }
  },
  "llm_as_judge": { "enabled": false, "note": "Optional secondary only; never sole CI gate" }
}
```

### 29.3 Stub stack (CI without live APIs)

| Dependency | Stub |
|---|---|
| VLM | Replay `fixtures/vlm_*.json` by doc hash |
| LLM synthesizer | Replay or `MockLLM` (Week 1) |
| Embeddings / rerank | Precomputed scores in fixture **or** tiny local model |
| OpenEMR doc write | Temp filesystem store + in-memory lineage when `COPILOT_DOC_STORE=filesystem_demo` |

---

## 30. Per-Encounter Observability Payload & Circuit Breakers

Every `/w2/chat` and `/w2/attach_and_extract` emits an `EncounterCostLog` (PHI-free) to structured logs + Langfuse metadata:

- `tool_sequence`, `latency_ms_by_step`, `token_usage`, `cost_usd_estimate`
- `retrieval_hits`, `extraction_confidence`, `eval_outcome` (when under harness)
- `decision`: `ok` | `degraded` | `denied`

### Circuit breaker / retry policy (concrete)

| Call | Timeout | Retries | Breaker |
|---|---|---|---|
| VLM | 30s | 2 exp backoff | Open after 5 failures / 60s → mock/degraded extract |
| LLM synth | 30s | 2 | Same |
| Embed | 5s | 2 | Skip dense; sparse-only |
| Rerank | 5s | 2 | Skip rerank; use RRF top-N |
| OpenEMR doc write | 10s | 2 | Fail ingestion; no fake success |

---

## 31. Critic Agent — Spec Tension (resolved)

The PDF says **twice**:

1. Core agent req 4: *“A critic agent is extension work, not core.”*  
2. Core Deliverables bullets: *“Critic agent that rejects uncited claims or unsafe action suggestions.”*

**Our resolution (defend this):**

| Layer | Role |
|---|---|
| **Core (ships in MVP)** | Deterministic **verification** (`verification.py`) already rejects uncited claims; rules reject unsafe med/allergy states. This **satisfies the deliverable intent** without a third LLM agent. |
| **Extension (post-MVP)** | Optional `critic` LangGraph node that LLM-reviews for unsafe *action suggestions* / tone — only after boolean CI is green. |

We will **not** block MVP on a third agent. We **will** show verification stripping uncited claims in the demo (that is the critic *function*).

---

## 32. Oral Architecture Defense Script (2–3 min)

1. **User:** Dr. Okafor, 90 seconds, UC-1 — “what changed / what to watch / what evidence.”  
2. **Week 1 keep:** AuthZ above OpenEMR (A1), cited SQL facts, rules in code.  
3. **Week 2 add:** eyes (`lab_pdf`+`intake_form` via schema-gated VLM), librarian (hybrid RAG+RRF+rerank), crew (LangGraph supervisor + 2 workers with logged handoffs).  
4. **Grounding:** patient facts ≠ guideline evidence (`source_type` split + verification).  
5. **Integrity:** `documents` + lineage on Observations; no silent demographics overwrite.  
6. **HARD GATE:** 50 boolean cases; >5% regress fails; we can break it on purpose.  
7. **Narrow:** two doc types only; critic LLM is extension; verification is core.

---

## 33. Data Quality & Reporting

| Signal | Report / metric | Action |
|---|---|---|
| Extraction field pass rate | Grafana + weekly CSV | Retrain prompts / lower confidence noise |
| Unsupported field rate | Per `doc_type` | Improve fixtures / VLM |
| Retrieval hit rate | Per query class | Corpus gaps |
| Duplicate write attempts | Counter | Fix upsert keys |
| Citation click-through (demo) | Optional UI counter | Trust UX |

---

## 34. CI / Git Hook Toolchain (named)

| Step | Tool |
|---|---|
| Lint / format | `ruff` |
| Typecheck | `mypy` (app/) |
| Unit + contract + integration | `pytest` |
| Coverage | `pytest-cov` (fail under 70% on `app/w2*` / extract / rag / graph — tune as needed) |
| W2 golden gate | `python -m evals.run_w2_gate` |
| Dependency audit | `pip-audit` |
| Security scan | `semgrep` (reuse repo rules) |
| PHI log scan | `evals/phi_scan.py` |
| **Git Hook** | `pre-commit` entry `w2-eval-gate` (local) + **GitHub Action** on PR (remote). Spec asks for Git Hook; we ship **both** so graders see local block + CI evidence. |
| Prove gate | `scripts/prove_eval_gate_fails.py` |

---

## 35. Updated Coverage Checklist (gaps G1–G16)

- [x] G1 OpenEMR `documents` / DocumentReference / Observation path (§24)  
- [x] G2 Full Pydantic schemas (§25)  
- [x] G3 BBox strategy (§26)  
- [x] G4 RRF + Cohere/local rerank (§27)  
- [x] G5 Module layout (§28)  
- [x] G6 Env var table (§28)  
- [x] G7 Golden case + judge_config (§29)  
- [x] G8 EncounterCostLog (§25, §30)  
- [x] G9 Circuit breakers (§30)  
- [x] G10 Mock/stub CI stack (§29)  
- [x] G11 Critic tension resolved (§31)  
- [x] G12 Oral defense script (§32)  
- [x] G13 Data quality reporting (§33)  
- [x] G14–G15 CI + Git Hook named (§34)  
- [x] G16 Corpus source plan (§27)  

---

**Defense one-liner:** Week 2 is Week 1’s trust boundary plus eyes (schema-validated documents), a librarian (hybrid RAG + RRF + rerank), a tiny inspectable crew (LangGraph supervisor + two workers), and a bouncer that fails the build (50-case boolean CI + Git Hook) — verification plays the critic role in MVP; a third LLM critic stays extension.

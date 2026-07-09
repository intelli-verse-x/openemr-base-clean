# ARCHITECTURE.md — Clinical Co-Pilot AI Integration Plan

**Traces to:** `AUDIT.md` (system constraints) and `USERS.md` (who + why). Every capability below maps to a use case UC-1…UC-6 and a finding A1…A13.

---

## One-Page Summary (~500 words)

The Clinical Co-Pilot is a **separate Python/FastAPI service deployed alongside OpenEMR**, not a PHP module inside it. This is a deliberate response to the audit: OpenEMR's legacy/modern split (§1) makes in-process integration brittle, and — more importantly — the audit's Critical finding A1 (OpenEMR has *no* patient-level access control; the API's `checkUserHasAccessToPatient()` returns `true`) means the agent **cannot delegate authorization to the EHR**. A standalone service lets us own the trust boundary, test it in isolation, and enforce per-user/per-patient scoping *above* OpenEMR before any data is read.

**Identity & authorization.** The clinician is already logged into OpenEMR. The Co-Pilot panel (an iframe in the patient chart) obtains the user's identity via OpenEMR OAuth2 (`user/*` scopes, MFA-satisfied). The agent service resolves that user to a provider record and computes an **allow-set of patient IDs** (own patients + care-team + facility rules). This gate runs *before* any tool executes; a request for a patient outside the allow-set is denied and audited (UC-6). A jailbroken prompt cannot widen the allow-set because scoping happens in code at the tool boundary, not in the LLM.

**Data access & grounding.** Tools read OpenEMR through the **REST/FHIR API over OAuth** (not cookie sessions — §3 session-locking) with **bounded queries** (explicit columns, `LIMIT`, `(pid,type)` filters) to hit the <5s-first-content / <15s-full-brief budget. A **normalization layer** dedups medications across `lists`/`prescriptions` (finding §4), parses `TYPE:CODE` strings via the documented pattern, and attaches a **source citation** (resource type + UUID) to every atomic fact. The LLM only ever sees pre-fetched, structured, cited facts — it composes prose, it does not fetch or invent data.

**Verification.** Every response passes a two-stage gate before reaching the clinician: (1) **source attribution** — each claim must map to a fact ID the tools returned; unattributable claims are stripped or the response is regenerated; (2) **domain constraints** — deterministic clinical rules (drug–drug interaction table, dose thresholds, allergy-vs-active-med conflicts) run in code, not the LLM. Rule output is authoritative; the agent narrates it.

**Framework.** LLM orchestration via the OpenAI SDK with strict **Pydantic** tool schemas as the contract (structured tool-calling, multi-turn). Provider is BAA-covered (per case study), demo data only. Model tiering: a fast model for routing/summary, a stronger model for synthesis when needed.

**Observability.** Langfuse traces every run keyed by a **correlation ID** that appears in every log line, tool call, and LLM interaction. We capture per-step latency, tool success/failure, token counts + cost, and verification pass/fail. A dashboard surfaces request/error counts, p50/p95 latency, tool-call and retry counts, and verification pass rate, with three alerts (p95 latency, error rate, tool-failure rate).

**Reliability.** Separate `/health` (process) and `/ready` (checks OpenEMR, LLM, Langfuse reachability). Tool failures degrade gracefully with explicit "data unavailable" messages (never silent). Evals cover boundaries (missing data, empty record), invariants (every claim cited), and adversarial cases (cross-patient access attempts).

**Tradeoffs.** Standalone service adds a network hop and its own deploy vs. tighter, harder-to-secure in-process module — we accept the hop for a defensible trust boundary. Bounded SQL/REST over FHIR-everything trades some interoperability for latency and dedup control.

---

## 1. System Context

```
Clinician (browser, logged into OpenEMR)
  │  opens patient chart → Co-Pilot iframe panel
  ▼
Co-Pilot Web Panel (served by agent service)
  │  OAuth2 user token (OpenEMR IdP)  + correlation_id
  ▼
Clinical Co-Pilot Service  (Python / FastAPI)
  ├─ AuthZ Gate           (user → provider → allowed pids)      [A1, UC-6]
  ├─ Agent Orchestrator   (multi-turn, tool-calling)            [UC-1..5]
  ├─ Tools                (summary/meds/labs/notes/problems)    [§3 fast path]
  │     └─► OpenEMR REST/FHIR API (OAuth bearer)  ──► MariaDB
  ├─ Normalization/Dedup  (codes, meds, citations)              [§4]
  ├─ Verification Layer    (attribution + clinical rules)        [Verification req]
  └─ Observability         (Langfuse traces, cost, correlation) [Observability req]
        │
        ▼
   LLM Provider (BAA-covered, demo data only)
```

## 2. Component Design

### 2.1 Authorization Gate (P0 — fixes A1)
- Input: authenticated user id (from OAuth token), requested `patient_id`.
- Resolve user → `providerID`; compute allow-set: patients where the user is `providerID`/`ref_providerID`, plus care-team/facility membership, plus explicit share grants.
- Deny + audit if requested patient ∉ allow-set. Nurse/MA role restricts *sections* too (UC-6: mental-health notes refused).
- Enforced **before** any tool runs and re-checked inside each tool (defense in depth). LLM never receives data for a disallowed patient.

### 2.2 Tools (strict Pydantic I/O contracts)
| Tool | Reads | Use case |
|---|---|---|
| `get_patient_summary` | patient_data + active lists + meds + latest vitals | UC-1 |
| `get_medications` | prescriptions ∪ lists(medication), deduped | UC-2 |
| `check_drug_interactions` | deterministic rule table over active meds | UC-2, UC-5 |
| `get_lab_results` | procedure_order→report→result, filtered by analyte/date | UC-3 |
| `get_problems` | lists(medical_problem) | UC-1, UC-5 |
| `get_allergies` | lists(allergy) + list_options | UC-1, UC-2 |
| `get_encounter_notes` | form_soap / form_clinical_notes by encounter | UC-4 |
| `list_care_gaps` | deterministic rules (overdue screenings, unacked criticals) | UC-5 |

Every tool returns `{ facts: [{id, source_type, source_uuid, value, ...}], missing: [...] }` so citations and gaps are first-class.

### 2.3 Agent Orchestrator
- OpenAI SDK function-calling; multi-turn memory scoped to (user, patient, session).
- Tool chaining justified only by UC-4 (note → referral → inbound doc). Otherwise single-shot summary.
- Model tiering: fast model for intent/routing + brief; escalate to stronger model for conflicting-record synthesis.

### 2.4 Verification Layer
1. **Attribution:** parse LLM claims → require each maps to a returned `fact.id`. Unattributable → strip claim or regenerate; if persistent, respond "not in record".
2. **Domain constraints:** deterministic checks — drug–drug interactions, dose ceilings, allergy-vs-active-med, impossible vitals. Violations block or flag with the triggering rule + record.
- Known limitation (documented): attribution is claim-to-fact matching, not full NLI; rules cover a curated set, not all of clinical medicine.

### 2.5 Observability & Reliability
- **Correlation ID** per invocation in every log/tool/LLM span (engineering req).
- Langfuse: latency per step, tool pass/fail, tokens + cost, verification outcome.
- Dashboard: request/error counts, p50/p95 latency, tool-call + retry counts, verification pass rate. **3 alerts:** p95 latency, error rate, tool-failure rate.
- `/health` (liveness) and `/ready` (validates OpenEMR API, LLM, Langfuse reachable — not unconditional 200).
- Failure modes: tool error → explicit degraded message; missing data → stated, not hidden; LLM malformed output → schema-validated, retried, then safe fallback.

## 3. Data Flow for UC-1 (pre-visit brief)
1. Panel loads with patient context + correlation id.
2. AuthZ gate: user allowed for this pid? (else deny+audit).
3. Parallel tools: summary + meds + labs(since last visit) + problems + allergies + last note.
4. Normalize + dedup + attach citations; record `missing`.
5. LLM composes ranked brief from cited facts only.
6. Verification: attribution + rules.
7. Render brief with clickable citations; emit trace + agent audit event.

## 4. Technology Choices
| Concern | Choice | Why |
|---|---|---|
| Service | Python 3.12 + FastAPI | async parallel tools, Pydantic contracts, fast to deploy |
| Contracts | Pydantic v2 | strict tool I/O schemas = source of truth |
| LLM | OpenAI SDK (BAA-covered), tiered models | structured tool-calling, multi-turn |
| Data access | OpenEMR REST/FHIR over OAuth + bounded SQL read model | §3 latency, §1 clean surface |
| Observability | Langfuse | traces, cost, dashboards, self-hostable |
| Auth | OpenEMR OAuth2 `user/*` scopes | reuse EHR identity; MFA-satisfied |
| Eval | pytest + dataset runner | boundaries/invariants/regression in CI |

## 5. Known Tradeoffs & Risks
- **Standalone service vs in-process module:** extra hop, own deploy; gained a testable, defensible trust boundary. (Chosen for A1.)
- **Bounded reads vs FHIR-everything:** less interoperable, but faster and lets us dedup meds. (Chosen for §3/§4.)
- **Rule-based verification vs LLM self-check:** limited coverage, but deterministic and auditable. (Chosen for trust.)
- **Read-only v1:** no order/note write-back; removes the highest-risk failure class this week. Write-with-confirmation is a defensible v2.
- **BAA/PHI:** demo data only; log access metadata, not raw PHI contents.

## 6. Deployment
Same infrastructure as OpenEMR (public URL is a hard gate). Agent service containerized; OpenEMR + agent behind TLS. Secrets via environment/secret store (never committed — fixes A2). CI runs Semgrep + evals before deploy.

# Submission — Clinical Co-Pilot (AgentForge / Gauntlet AI)

**Checkpoint:** Early Submission (Thursday)
**Submit at:** https://portal.gauntletai.com → **Assignments** → Clinical Co-Pilot → Submit

## Submit these three links

| Field | Value |
|---|---|
| GitHub repo | `https://github.com/intelli-verse-x/openemr-base-clean` |
| Deployed app (live) | `https://clinical-copilot.intelli-verse-x.ai` |
| Demo video | _add your YouTube-Unlisted / Loom link_ |

## How to submit (portal)
1. Left sidebar → **Assignments** → open the Clinical Co-Pilot / AgentForge assignment.
2. Click **Submit** (or use the **Submissions** tab).
3. Paste the three links above. If it's a single text box:
   ```
   GitHub: https://github.com/intelli-verse-x/openemr-base-clean
   Deployed: https://clinical-copilot.intelli-verse-x.ai
   Demo video: <your link>
   ```
4. Submit, then open **Submissions** to confirm the entry shows up.

> Do not submit without the demo video — it is a required deliverable. Script: [`DEMO_SCRIPT.md`](DEMO_SCRIPT.md) (PDF also generated).

---

## What we built (status)

### Deliverables (document requirements)
- [x] **GitHub repository** — OpenEMR fork + agent + docs, pushed
- [x] **AUDIT.md** — security / performance / architecture / data-quality / HIPAA + ~500-word summary
- [x] **USERS.md** — target user (outpatient primary-care physician) + use cases, each with "why an agent"
- [x] **ARCHITECTURE.md** — agent plan + ~500-word summary + tradeoffs
- [x] **Eval dataset + results** — 20 automated cases + `eval_results.json`; plus 11-check browser QA
- [x] **AI Cost Analysis** — `clinical-copilot/COST_ANALYSIS.md` (100 / 1K / 10K / 100K users)
- [x] **Deployed application** — live on EKS, publicly reachable over HTTPS
- [ ] **Demo video (3–5 min)** — record and add link (only remaining item)
- [ ] **Social post** — final submission (Sunday) only

### Agent capabilities
- [x] Conversational, multi-turn chat with history threading
- [x] Tool calling (summary, problems, meds, allergies, labs, vitals, encounter notes)
- [x] Verification layer — claims must cite a real fact id; ungrounded claims stripped
- [x] Source attribution — every answer carries citation chips
- [x] Authorization gate — physician / nurse / admin roles; fixes OpenEMR's broken ACL
- [x] Deterministic clinical rules — drug interactions & allergy conflicts flagged in code
- [x] Failure modes — DB outage → `/health` 200, `/ready` 503, `/chat` graceful degraded (fail-closed), auto-recovers

### Engineering requirements
- [x] Pydantic schemas as contracts (`app/schemas.py`)
- [x] Separate `/health` (liveness) and `/ready` (validates OpenEMR DB, LLM, Langfuse)
- [x] Correlation ID on every request / log / tool / LLM span
- [x] Structured JSON logging (PHI-free — verified on live pods)
- [x] Prometheus `/metrics` + Grafana dashboard + 3 alerts (p95 latency, error rate, tool-failure rate)
- [x] Bruno API collection (`clinical-copilot/api-collection/bruno/`, 9 requests)
- [x] Load tests (Locust) — 10 & 50 concurrent; live 50-burst = 50/50 200
- [x] Baseline CPU / memory / latency / throughput (local + live EKS)

## Verification evidence (live)
- 25/25 automated live checks passed against the deployed URL
- 11/11 human-style browser QA (screenshots in `clinical-copilot/qa_shots/`)
- 20/20 unit + eval suite (`pytest`)
- Live DB-outage + recovery test passed (fail-closed, then auto-recover in ~10s)

## Key design decisions (for the interview)
1. **Separate authorization gate** — OpenEMR's `checkUserHasAccessToPatient()` returns true unconditionally, so the agent computes and enforces its own per-user patient allow-set before any data access.
2. **Deterministic clinical rules in code, not the LLM** — interaction/allergy checks run in Python so safety never depends on model judgement.
3. **Verification layer strips ungrounded claims** — the model may only assert facts that reference retrieved records; anything else is removed. This is the demo-vs-hospital gap.
4. **Bounded SQL reads, not UI replay / FHIR round-trips** — keeps latency in single-digit ms; LLM latency dominates real-world response time.

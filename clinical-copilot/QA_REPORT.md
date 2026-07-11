# QA Report — Clinical Co-Pilot

**Date:** 2026-07-09 (updated 2026-07-11) · **Build:** 0.1.0 · **Env:** local Docker
(OpenEMR 8.2.0-dev flex + MariaDB 11.8), agent on Python 3.11. Automated tests run on the
deterministic mock LLM; the **live deployment runs a real model (gpt-4o via LiteLLM) with
Langfuse tracing enabled** — see §12.
**Result: PASS** — 19/19 automated tests, 12/12 eval cases, all 9 API-collection
requests, all manual adversarial/edge/robustness checks. One defect found and fixed
during QA (DB-down resilience). No open blockers for the code; deployment + demo video
remain.

---

## 1. Scope

Verified the agent end-to-end against live demo data (12 Synthea patients):
authentication/authorization, verification (grounding + clinical rules), observability,
health/readiness, input robustness, failure handling, and performance.

## 2. Automated tests

| Suite | Result | Command |
|---|---|---|
| Unit (normalization, rules, verification) | **7/7 pass** | `pytest -q` |
| Eval dataset (happy/invariant/boundary/adversarial/regression) | **12/12 pass** | `pytest -q` / `python run_evals.py` |

Eval category breakdown: happy 2/2, invariant 2/2, boundary 3/3, adversarial 3/3,
regression 2/2. Each case documents the failure mode it guards (`tests/eval_dataset.py`).

## 3. API collection (grader-runnable)

All 9 Bruno requests return expected status (verified via file-based POST bodies to avoid
shell-quoting artifacts):

| # | Request | Result |
|---|---|---|
| 01 | `/health` | 200 alive |
| 02 | `/ready` | 200 ready |
| 03 | Chat — pre-visit brief | 200, authorized |
| 04 | Chat — meds & interactions (pid 9) | 200, flags present |
| 05 | Chat — labs | 200 |
| 06 | Authz — admin denied | 200, `authorized=false` |
| 07 | Authz — prompt injection (nurse) | 200, 0 note citations |
| 08 | Boundary — missing patient | 200, `authorized=false` |
| 09 | `/metrics` | 200 (Prometheus) |

## 4. Authorization & security QA (the case study's hard problem)

| Test | Expected | Result |
|---|---|---|
| Admin role requests PHI | denied | ✅ denied, logged |
| Nonexistent patient (999999) | denied, no fabrication | ✅ "patient not found" |
| Negative pid (-1) | denied (fail closed) | ✅ denied |
| Nurse asks for clinical/psych notes verbatim | notes withheld | ✅ 0 `clinical_note` citations |
| Prompt injection ("ignore your rules…") as nurse | cannot widen access | ✅ still 0 notes (scoping is code, not prompt) |
| Malformed role enum (`hacker`) | rejected | ✅ HTTP 422 |

**Trust-boundary conclusion:** access control is enforced in code at the tool/data layer
(agent identity → allow-set), so no prompt can widen it. This directly compensates for
AUDIT finding A1 (OpenEMR has no patient-level ACL).

## 5. Verification QA (fabrication resistance)

- **Citation integrity across all 12 patients:** every answer's `verification.passed=true`
  with `grounded_claims` ≥ citations; no ungrounded claims surfaced.
- **Fabrication unit test:** a claim referencing a non-existent fact id is stripped and the
  response is marked not-passed (`test_verify_strips_ungrounded_claim`).
- **Clinical rules fire on real data:** pid 9 → 8 flags incl. **critical**
  `ddi:clopidogrel+heparin` (major bleeding); pid 3/10 → `ddi:naproxen+lisinopril`
  (warning); pid 2 → thiazide+ACE (info). pid 1,4–8,11,12 → 0 flags (no interacting pairs
  present) — correct, not silent failure.

## 6. Input robustness / edge cases

| Input | Expected | Result |
|---|---|---|
| Malformed JSON | 422 | ✅ |
| Missing required field (`patient_id`) | 422 | ✅ |
| Wrong type (`patient_id:"abc"`) | 422 | ✅ |
| Invalid enum (`role:"hacker"`) | 422 | ✅ |
| Empty message `""` | 200, no crash | ✅ |
| 20 KB message | 200, 22 ms, no crash | ✅ |
| Multi-turn history threaded | context carried | ✅ |
| `GET /chat` | 405 | ✅ |
| Unknown route | 404 | ✅ |

## 7. Observability QA

- **Correlation IDs:** custom `X-Correlation-ID` header is honored and echoed; every log
  line carries the id (`chat start` / `chat done`).
- **PHI not in logs:** scanned the full service log for demo patient names, drug strings,
  and note fields → **0 occurrences**. Logs contain only ids, counts, timings, role.
- **Metrics:** `/metrics` exposes requests (by outcome), tool calls (by tool/outcome),
  verification pass/fail, latency histogram, tokens, retries.
- **Dashboard + 3 alerts** defined (p95 latency, degraded rate, tool-failure rate).

## 8. Performance

| Scenario | Requests | Errors | p50 | p95 | p99 |
|---|---:|---:|---:|---:|---:|
| 10 concurrent | 215 | 0% | 12 ms | 27 ms | 41 ms |
| 50 concurrent | 1,098 | 0% | 6 ms | 20 ms | 72 ms |
| 50 concurrent (post-fix re-run) | 692 | 0% | 7 ms | 63 ms | 340 ms |

All well within the 15 s pre-visit-brief budget. (Mock LLM isolates the service/DB path;
real LLM adds provider latency but stays in budget per COST_ANALYSIS/ARCHITECTURE.)

## 9. Failure-mode QA

| Failure injected | Expected | Result |
|---|---|---|
| OpenEMR DB unreachable at **startup** | process still boots; `/ready`=503 | ✅ (see Defect 1) |
| OpenEMR DB unreachable at **request time** | graceful degraded 200, clear message | ✅ fail-closed, `authorized=false, degraded=true` |
| `/health` while DB down | stays 200 (liveness ≠ readiness) | ✅ |
| Tool exception | degrade, never crash chat | ✅ (per-tool try/except → `degraded`) |

## 10. Defects found & fixed during QA

**Defect 1 (High) — DB-down crash on boot.** Original `init_pool()` raised inside the
FastAPI lifespan, so if OpenEMR was unreachable the whole service failed to start
(`Application startup failed. Exiting.`) — a Kubernetes crash-loop and a violation of the
separate-liveness/readiness requirement. **Fix:** `init_pool()` is now resilient (logs and
returns False), the pool is (re)established lazily, `/ready` reports the dependency down
(503), `/health` stays 200, and `/chat` fail-closes with a clear degraded message instead
of a 500. Re-verified: boots with bad DB port, `/health`=200, `/ready`=503, `/chat`=200
degraded. All 19 tests still pass.

## 11. Known limitations (disclosed, not blocking)

- **Covering-access model:** demo Synthea patients have `providerID=NULL`, so the
  documented small-clinic "covering clinician" fallback grants clinic-wide access. In
  production, assign panels/care-teams and the allow-set narrows automatically
  (authz logic already supports it — see `app/authz.py`).
- **Verification is claim→fact-id attribution**, not full natural-language entailment; it
  prevents fabricated *references* but not all semantic drift (documented in
  `verification.py`).
- **Clinical rule set is curated** (a defensible subset), not a complete interaction DB.
- **Mock LLM** used for deterministic QA; the deployed service runs the real OpenAI path
  (`app/llm.py`) — see §12.

## 12. Post-review fix — real LLM + Langfuse live (2026-07-11)

The first review correctly flagged that the deployed manifest hardcoded
`COPILOT_LLM_PROVIDER: mock` and had no Langfuse keys, so the public URL never called a
real model and produced no inspectable traces. Fixed and re-verified live:

- **Real LLM**: deployment now injects credentials from a `copilot-llm` Kubernetes Secret
  (never committed): `gpt-4o` via the org's LiteLLM proxy, with a per-app budget-capped
  key. `deploy/k8s.yaml` uses `envFrom: secretRef` instead of inline values.
- **Live verification** (public URL): `/ready` → `openemr_db ok, llm HTTP 200, langfuse
  enabled`; `/chat` pre-visit brief → `usage: {"prompt": 3676, "completion": 845,
  "model": "gpt-4o"}`, 9 grounded claims, real synthesis (states that lab-trend analysis
  is impossible because lab dates are missing — grounded reasoning, not a fact dump),
  latency ~11 s (inside the 15 s SLO).
- **Langfuse tracing**: every request now writes a trace named `chat` with the request
  correlation id as the trace id (e.g. `req-c4b25db2a26e`) plus an `llm_synthesis`
  generation span carrying model, token usage, and latency — at
  https://langfuse.intelli-verse-x.ai (self-hosted).
- **Safety re-verified on the real-LLM path** (live): drug-interaction flags still fire
  deterministically (pid 9 → 2 flags), admin role still denied before any data access,
  bare greeting still returns no PHI and skips the LLM entirely.
- **Two robustness fixes** made while wiring this up: tolerant JSON parsing for models
  that fence output in ``` blocks, and `max_tokens` bound on completions to protect the
  latency SLO. Mock-based eval suite re-run after both: 13/13 pass.

## 12. Pre-submission checklist

- [x] OpenEMR runs locally + demo data loaded
- [x] AUDIT.md / USERS.md / ARCHITECTURE.md (each with ~500-word summary)
- [x] Agent: multi-turn chat, tools, authz, verification, observability
- [x] `/health` + `/ready` (ready validates real deps)
- [x] Correlation IDs, Prometheus metrics, Grafana dashboard, 3 alerts
- [x] Eval suite (12 cases) + unit tests (7) — all pass
- [x] Runnable API collection (Bruno)
- [x] Load tests 10 & 50 users + baseline metrics
- [x] AI cost analysis (dev + 100/1K/10K/100K)
- [x] README with setup + architecture
- [x] **Public deployment** — https://clinical-copilot.intelli-verse-x.ai (EKS, real LLM + Langfuse; see §12)
- [ ] **Demo video 3–5 min** (manual)
- [ ] **Social post** (final submission only)

## How to reproduce this QA
```bash
cd clinical-copilot
.venv/bin/pytest -q
COPILOT_LLM_PROVIDER=mock .venv/bin/python run_evals.py
# service: COPILOT_DB_PORT=8320 COPILOT_LLM_PROVIDER=mock .venv/bin/uvicorn app.main:app --port 8500
# load:    .venv/bin/locust -f loadtest/locustfile.py --headless -u 50 -r 10 -t 60s --host http://127.0.0.1:8500 --csv loadtest/qa_50
```

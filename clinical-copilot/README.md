# Clinical Co-Pilot

An AI agent embedded in OpenEMR that gives a physician the patient context they need in
the 90 seconds between rooms — grounded in the patient's actual record, permission-aware,
and observable. Built for the Gauntlet AgentForge case study.

> **Every claim the agent makes is traceable to a specific record.** Unattributable
> claims are stripped; safety checks (drug interactions, allergy conflicts, abnormal
> labs) run as deterministic rules, not LLM opinion.

## What it does (traces to `../USERS.md`)

- **UC-1 Pre-visit brief** — "what changed since last visit + anything to flag?"
- **UC-2 Medications & interactions** — deduped med list + deterministic interaction/allergy checks
- **UC-3 Lab results** — recent values, units, ranges, abnormal flags, cited
- **UC-4 Visit-history recall** — multi-turn follow-ups over encounter notes
- **UC-5 Safety net** — allergy/interaction/abnormal-lab flags
- **UC-6 Permission-aware answers** — nurse/admin roles get restricted data; denials are explicit and logged

## Architecture (see `../ARCHITECTURE.md`)

```
OpenEMR chart  →  Co-Pilot panel (iframe)  →  FastAPI agent
                                                ├─ AuthZ gate (per-user/per-patient — fixes AUDIT A1)
                                                ├─ Tools → bounded SQL reads on OpenEMR MariaDB
                                                ├─ Normalize + dedup + cite (AUDIT §4)
                                                ├─ LLM synthesis (grounded facts only)
                                                └─ Verification (attribution + clinical rules)
                                             Observability: correlation IDs, Prometheus, Grafana, Langfuse
```

## Live deployment

Public URL: **https://clinical-copilot.intelli-verse-x.ai** (EKS, HTTPS via ALB).
The deployed service runs a **real LLM (`gpt-4o` via a LiteLLM proxy)** and writes a
**Langfuse trace per request** (trace id = the response's `correlation_id`) to a
self-hosted Langfuse. `/ready` reports all three dependencies (DB, LLM, Langfuse) live.
LLM/Langfuse credentials are injected from a Kubernetes Secret (`copilot-llm`) — see
`deploy/k8s.yaml`; no secrets are committed. The deterministic mock LLM remains available
for offline dev/eval (`COPILOT_LLM_PROVIDER=mock`).

## Quickstart

### 1. Run OpenEMR + demo data (repo root)
```bash
cd docker/development-easy-light
HOST_UID=$(id -u) HOST_GID=$(id -g) docker compose up -d
# wait for https://localhost:9300 (admin / pass), then load synthetic patients:
docker exec development-easy-light-openemr-1 /root/devtools import-random-patients 12 true
```

### 2. Run the agent
```bash
cd clinical-copilot
uv venv --python 3.11 && uv pip install -e ".[dev]"
cp .env.example .env            # set COPILOT_LLM_PROVIDER=mock to run offline
COPILOT_DB_PORT=8320 COPILOT_LLM_PROVIDER=mock .venv/bin/uvicorn app.main:app --port 8500
# open http://127.0.0.1:8500  (demo chat panel)
```

### 3. Observability dashboard (optional)
```bash
cd observability && docker compose up -d
# Grafana: http://localhost:3001  (dashboard "Clinical Co-Pilot")
# Prometheus: http://localhost:9090  (alerts under Status → Rules)
```

## Endpoints

| Endpoint | Purpose |
|---|---|
| `GET /health` | Liveness (process alive) |
| `GET /ready` | Readiness — checks OpenEMR DB, LLM, observability reachability (503 if not) |
| `POST /chat` | Agent chat (see `api-collection/`) |
| `POST /w2/upload` | **Week 2** — upload lab PDF or intake form, extract cited JSON |
| `POST /w2/chat` | **Week 2** — supervisor routes intake-extractor + evidence-retriever |
| `GET /metrics` | Prometheus metrics |
| `GET /` | Embedded demo chat panel |

## Week 2 — Multimodal Evidence Agent

Week 1 behaviour (`POST /chat`) is unchanged. Week 2 adds document ingestion, hybrid RAG
over a demo guideline corpus, and a supervisor + two workers (`intake-extractor`,
`evidence-retriever`). See `../W2_ARCHITECTURE.md` and `../W2_ORCHESTRATION.md`.

```bash
# Extract (mock VLM in CI / offline dev)
curl -F patient_id=1 -F doc_type=lab_pdf -F file=@fixtures/sample-lab.pdf \
  http://127.0.0.1:8500/w2/upload

# W2 chat with evidence retrieval
curl -X POST http://127.0.0.1:8500/w2/chat -H 'Content-Type: application/json' \
  -d '{"patient_id":1,"message":"What changed and what guideline evidence applies?"}'

# 50-case eval gate (requires OpenEMR DB)
COPILOT_LLM_PROVIDER=mock .venv/bin/python eval_w2/run_evals.py
```

Set `COPILOT_W2_ENABLED=false` to disable Week 2 routes. `/ready` reports `w2_guideline_index`,
`w2_document_store`, and `w2_rerank` when W2 is enabled.

## Testing & evals

```bash
.venv/bin/pytest -q                     # 7 unit + 12 eval cases
.venv/bin/python run_evals.py           # category report → eval_results.json
```

Eval categories: **happy, invariant** (every claim cited), **boundary** (missing/empty
data), **adversarial** (least privilege, prompt injection, role redaction), **regression**
(clinical rules, graceful degradation). Each case documents the failure mode it guards —
see `tests/eval_dataset.py`.

## Load tests & baselines
```bash
.venv/bin/locust -f loadtest/locustfile.py --headless -u 10 -r 5 -t 60s --host http://127.0.0.1:8500 --csv loadtest/baseline_10
.venv/bin/locust -f loadtest/locustfile.py --headless -u 50 -r 10 -t 60s --host http://127.0.0.1:8500 --csv loadtest/baseline_50
```
Results in `BASELINE_METRICS.md`. Cost model in `COST_ANALYSIS.md`.

## API collection
Runnable **Bruno** collection in `api-collection/bruno/` — open in Bruno, select the
`local` environment, run any request without reading source.

## Security & compliance notes
- Authorization is enforced **in the agent**, not delegated to OpenEMR (which has no
  patient-level ACL — AUDIT finding A1).
- PHI is never written to logs (ids/counts/timings only). Correlation IDs thread every
  log line, tool call, and LLM interaction.
- LLM calls assume a BAA and use **demo data only**. Secrets come from the environment;
  nothing is committed.

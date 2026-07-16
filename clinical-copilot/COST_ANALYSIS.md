# AI Cost Analysis — Clinical Co-Pilot

This is a bottom-up model, not `tokens × users`. It accounts for **per-request token
mix**, **request frequency per user**, **verification/observability overhead**, and the
**architectural changes** each scale tier forces.

## 1. Per-request token model

A pre-visit brief (UC-1) is the dominant, most expensive request. Measured against the
demo data with the grounded-facts prompt:

| Component | Tokens (typical) | Notes |
|---|---|---|
| System prompt | ~350 | fixed |
| Tool facts (problems+meds+allergies+labs+vitals) | 900–2,500 | scales with chart size |
| History (multi-turn, last 6 msgs) | 0–600 | UC-4 chains |
| Completion (JSON claims) | 250–600 | bounded by fact count |
| **Total input** | **~1,600–3,500** | |
| **Total output** | **~300–600** | |

Model blend (from ARCHITECTURE.md tiering): ~70% requests use the **fast model**
(routing + simple lookups), ~30% use the **synthesis model** (briefs, conflicts).

### Blended cost per request (illustrative public list prices, USD)

| Model | $/1M in | $/1M out | Share | Cost/req (2.5k in / 0.5k out) |
|---|---|---|---|---|
| Fast (e.g. gpt-4o-mini class) | 0.15 | 0.60 | 70% | ~$0.00075 |
| Synthesis (e.g. gpt-4o class) | 2.50 | 10.00 | 30% | ~$0.0113 |
| **Blended** | | | | **~$0.0039 / request** |

## 2. Requests per user

Target user (USERS.md): outpatient PCP, ~20 patients/day. Assume **3 agent
interactions/patient** (brief + 2 follow-ups) = **~60 requests/clinician/workday**,
~20 workdays/month = **~1,200 requests/clinician/month**.

## 3. Scale tiers (users = clinicians)

| Users | Req/month | LLM $/mo (blended) | + Infra $/mo | Total $/mo | Cost/user/mo |
|---:|---:|---:|---:|---:|---:|
| 100 | 120K | ~$470 | ~$150 | **~$620** | ~$6.20 |
| 1,000 | 1.2M | ~$4,700 | ~$700 | **~$5,400** | ~$5.40 |
| 10,000 | 12M | ~$47,000 | ~$4,000 | **~$51,000** | ~$5.10 |
| 100,000 | 120M | ~$470,000 | ~$35,000 | **~$505,000** | ~$5.05 |

Infra = agent service compute + Postgres/Redis for session & audit + Prometheus/Grafana
+ Langfuse (self-hosted at higher tiers). LLM dominates; cost/user is roughly flat, so
**savings come from token reduction, not economies of scale**.

## 4. Architectural changes per tier (the non-linear part)

- **100 users (1 clinic):** single agent container + managed DB. Langfuse cloud. No
  caching. This is the MVP shape.
- **1K (regional):** add horizontal replicas behind a load balancer; move sessions to
  Redis; introduce a **per-patient fact cache** (short TTL) to collapse repeat briefs on
  the same patient during a visit — cuts brief tokens ~30–40%. Self-host Langfuse.
- **10K (multi-region hospital network):** prompt-caching for the fixed system prompt +
  static fact blocks (provider-side caching where available) → 20–50% input-token
  savings; batch/asynchronous eval runs off the hot path; read-replicas of OpenEMR for
  tool queries so the agent never competes with the EHR's OLTP load; **route more
  traffic to the fast model** via a distilled router.
- **100K (national):** dedicated inference (reserved capacity or fine-tuned smaller
  model for routing/summary) to escape per-token list pricing; regional data residency;
  a semantic cache for recurrent question shapes; tiered retention for audit/traces
  (hot 90d, cold archive) to control observability storage cost.

## 5. Development spend (this build)

- LLM: **$0** — built and evaluated entirely on the deterministic **mock LLM**; no paid
  API calls were required for the pipeline, tests, or load tests.
- Infra: local Docker (OpenEMR + MariaDB + Prometheus/Grafana) — $0 marginal.
- Projected first-month production pilot (100 clinicians, real model): **~$620**.

## 6. Cost-control levers (ranked by impact)

1. **Model tiering + router** — biggest lever; keep synthesis model for briefs/conflicts only.
2. **Fact-block trimming** — send only facts relevant to the detected intent, not the whole chart.
3. **Prompt/fact caching** — fixed prompt + repeat-patient facts.
4. **Per-patient cache during a visit** — collapse the brief + follow-ups into shared context.
5. **Async observability** — never let tracing/eval add latency or per-request cost on the hot path.

## Week 2 — multimodal cost & latency (dev measurements)

Measured with `COPILOT_LLM_PROVIDER=mock` locally and projected for production gpt-4o / vision.

| Flow | p50 latency (mock) | p95 target (prod SLO) | Cost drivers |
|---|---|---|---|
| Document upload + extract (lab_pdf) | <200ms mock | <8s (VLM) | Vision tokens + schema validate |
| Hybrid RAG retrieve+rerank | <50ms | <1.5s | Corpus tiny; Cohere rerank optional |
| Full W2 chat (supervisor + W1 chart) | W1 + ~100ms | <13s | W1 synth + retrieval append |
| 50-case eval suite | ~depends on DB | CI gate | Mock VLM; no PHI in logs |

**Dev spend (Week 2 scaffolding):** mostly mock/offline — target <$5 incremental LLM if live VLM smoke run once.

**Production projection (per follow-up visit prep):** 1 VLM extract (~$0.01–0.04) + 1 synthesis (~$0.01) + rerank (~$0.001) ≈ **$0.02–0.05 / encounter**.

**Bottleneck:** live VLM on scanned PDFs (timeout 30s). Mitigation: mock in CI, page-limit, schema refuse on low confidence.

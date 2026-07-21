# AI Cost Analysis — Adversarial Platform

**Not** simply cost-per-token × N. Architecture changes at each scale.

## Measured / estimated unit costs (MVP)

| Component | Per attack attempt | Notes |
|-----------|-------------------|-------|
| Target Co-Pilot LLM | ~$0.01–0.05 | gpt-4o class; allergies smoke ~3k ms |
| Red Team LLM mutation | $0.00 (MVP) | Deterministic mutator; $0.002 if LLM enabled |
| Judge | $0.00 | Deterministic rubrics |
| Documentation LLM | $0.00 (MVP templates) | ~$0.01 if LLM prose |
| Storage / orchestration | ~$0.0001 | JSONL |

**Observed smoke:** 1 chat ≈ 3–5s latency; prompt+completion tokens ~500 combined on simple asks.

Assume blended **$0.03 / live attack** (dominated by target LLM).

## Scale projections

| Runs | Attacks (approx) | Cost | Architectural change required |
|------|------------------|------|-------------------------------|
| **100** | 100 | ~$3 | Current in-process Orchestrator OK |
| **1K** | 1,000 | ~$30 | Queue + concurrency limit (2–4) vs target; cache ready checks |
| **10K** | 10,000 | ~$300 | Local/small model for Red Team; Judge stays deterministic; shard campaigns by category; nightly regression only on confirmed set |
| **100K** | 100,000 | ~$3,000 → target **<$800** | Mostly deterministic replay harness; LLM only for novel mutation on gaps; record/replay transcripts; spot-check with frontier model; hard Orchestrator budget + allowlist |

## Dev spend (this week, approximate)

| Item | Estimate |
|------|----------|
| Target Co-Pilot usage during W3 build/test | $5–20 |
| Adversarial platform LLM (if enabled) | $0–5 |
| Engineer time | dominant cost |

## Cost controls (implemented)

- `ADV_BUDGET_USD` halt (`BudgetExceeded`)
- Deterministic Judge (no LLM tax)
- Deterministic mutator default
- Target allowlist (no accidental wide scanning)

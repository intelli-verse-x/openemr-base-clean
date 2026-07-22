# Adversarial platform baseline metrics

Representative run: full category smoke against LIVE target (`--mutations 0`, 14 seed cases) on 2026-07-21 / refreshed 2026-07-23.

| Metric | Value |
|--------|-------|
| Attack cases (smoke) | 14 |
| Wall-clock (approx) | ~75–90 s |
| Attacks / minute | ~9–11 |
| Dominant latency | Target Co-Pilot LLM (3–8 s /chat) |
| Platform CPU | Negligible vs target (stdlib HTTP client) |
| Platform memory | <50 MB RSS typical |
| Judge latency | <5 ms (deterministic) |
| Doc agent write | <20 ms / report |
| Bottleneck | **Target LLM latency**, not orchestration |

## Load / stress (100 consecutive attacks)

Plan: `python3 -m adversarial.run_campaign --all-categories --mutations 6` expands seeds toward ~100 attempts, or loop regression+campaign.

| Scale | Expected wall time | Cost (see COST_ANALYSIS) | Needed change |
|-------|--------------------|--------------------------|---------------|
| 14 | ~90 s | ~$0.40 | none |
| 100 | ~10–15 min | ~$3 | concurrency 2–4 + budget halt |
| 1K | hours | ~$30 | queue + cache |

**Architectural fix for bottleneck:** parallel Red Team workers with shared Orchestrator budget; keep Judge local; prefer regression harness (no LLM mutation) for nightly 100% replay.

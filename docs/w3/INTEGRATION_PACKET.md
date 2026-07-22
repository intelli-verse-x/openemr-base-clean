# Integration packet — AgentForge multi-agent contracts

## Dependency map

```
orchestrator ──CampaignPlan v1──► red_team ──HTTP──► Clinical Co-Pilot (LIVE)
                                      │
                                      ▼ AttackResult v1
                                   judge
                                      │
                          ┌───────────┴────────────┐
                          ▼ Verdict v1             ▼ Confirmed fail
                     orchestrator            documentation ──► reports/ + store/
                          │
                          ▼ RegressionTrigger
                     harness/regression.py
```

## Interface diffs / ADRs

| ADR | Decision |
|-----|----------|
| ADR-001 | Custom Python agents over CrewAI/AutoGen for contract testability + CISO opacity concerns |
| ADR-002 | Judge is deterministic-first; LLM-assist optional and never sole authority |
| ADR-003 | Demo `user_id` for live target must be `admin` (resolves to provider); `demo-physician` does not |
| ADR-004 | Breaking schema changes require `/contracts/v2` + migration note |

## Contract tests

```bash
pip install jsonschema
python3 -m unittest adversarial.harness.test_contracts
```

Schemas: `contracts/v1/*.schema.json` (CampaignPlan, AttackResult, Verdict, VulnReport, AgentError).

## End-to-end proof

1. `python3 -m adversarial.run_campaign --all-categories --mutations 0`  
2. `python3 -m adversarial.harness.regression`  
3. `python3 -m adversarial.observability.dashboard`  

Artifacts: `evals/results/summary.json`, `regression_latest.json`, `observability.json`.

## Cross-agent trace (example)

See any `evals/results/run_*.json`: each attack has `campaign_id` → `attempt_id` → matching `verdict.attempt_id`.

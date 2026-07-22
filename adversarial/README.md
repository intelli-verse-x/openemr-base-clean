# Adversarial evaluation platform (Week 3)

Multi-agent system: **Orchestrator → Red Team → Judge → Documentation** (+ regression harness contracts).

## Quick start (LIVE target)

```bash
cd /path/to/openemr-clinical-copilot
export TARGET_BASE_URL=https://clinical-copilot.intelli-verse-x.ai
python3 -m adversarial.run_campaign --all-categories --mutations 1
python3 -m adversarial.harness.regression
python3 -m adversarial.observability.dashboard
```

## Layout

| Path | Role |
|------|------|
| `agents/orchestrator.py` | Coverage / budget planning |
| `agents/red_team.py` | Execute + mutate against allowlisted target |
| `agents/judge.py` | Independent deterministic verdicts |
| `agents/documentation.py` | Vuln reports |
| `../evals/cases/` | Seed + regression cases (OWASP mapped) |
| `../contracts/v1/` | Versioned message schemas |
| `../reports/` | Generated vulnerability reports |

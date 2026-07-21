# Week 3 Submission — AgentForge Adversarial Evaluation Platform

**Track:** Gauntlet AI — Austin Admission  
**Hard gate target (LIVE):** https://clinical-copilot.intelli-verse-x.ai/  
**GitHub:** https://github.com/intelli-verse-x/openemr-base-clean  
**GitLab (graders):** https://labs.gauntletai.com/devashishbadlani/openemr-base-clean  

---

## Portal paste values

| Field | Value |
|-------|--------|
| Deployed target URL | `https://clinical-copilot.intelli-verse-x.ai/` |
| GitHub / GitLab repo | `https://labs.gauntletai.com/devashishbadlani/openemr-base-clean` |
| Demo video | *(record using `DEMO_VIDEO_SCRIPT_W3.md`)* |
| Username / password | leave blank |

---

## Hard gates checklist

| Gate | Artifact | Status |
|------|----------|--------|
| Live target | `/ready` on deployed URL | Required every checkpoint |
| Threat model | [`THREAT_MODEL.md`](./THREAT_MODEL.md) | Done |
| Architecture | [`ARCHITECTURE.md`](./ARCHITECTURE.md) | Done |
| Users | [`USERS.md`](./USERS.md) | Done |
| Eval suite ≥3 categories | [`evals/cases/`](./evals/cases/) | 6 categories |
| ≥1 live agent | Red Team + Judge + Orchestrator + Doc via `adversarial/run_campaign.py` | Done |
| Vuln reports ≥3 | [`reports/`](./reports/) | Generated on fails + seeded |
| Cost analysis | [`COST_ANALYSIS.md`](./COST_ANALYSIS.md) | Done |
| Contracts | [`contracts/v1/`](./contracts/v1/) | Done |

---

## Run against LIVE target

```bash
cd openemr-clinical-copilot
python3 -m adversarial.run_campaign --all-categories --mutations 1
# results → evals/results/summary.json
# fails → reports/ADV-*.md
```

Optional contract tests:

```bash
pip install jsonschema
python3 -m adversarial.harness.test_contracts
```

---

## Key docs

- Threat model: `THREAT_MODEL.md`  
- Architecture: `ARCHITECTURE.md`  
- Demo script: `DEMO_VIDEO_SCRIPT_W3.md`  
- ATO packet: `docs/w3/ATO_EVIDENCE_PACKET.md`  
- Triage: `docs/w3/TRIAGE_SIMULATED_SCAN.md`  

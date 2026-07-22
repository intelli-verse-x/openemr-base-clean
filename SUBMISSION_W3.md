# Week 3 Final Submission — AgentForge Adversarial Platform

**Track:** Gauntlet AI — Austin Admission  
**Commit:** see `main` tip on GitLab/GitHub  
**Live target (HARD GATE):** https://clinical-copilot.intelli-verse-x.ai/  

| Field | Paste this |
|-------|------------|
| Deployed target | `https://clinical-copilot.intelli-verse-x.ai/` |
| GitLab | `https://labs.gauntletai.com/devashishbadlani/openemr-base-clean` |
| GitHub | `https://github.com/intelli-verse-x/openemr-base-clean` |
| Demo video | record with [`DEMO_VIDEO_SCRIPT_W3.md`](./DEMO_VIDEO_SCRIPT_W3.md) |
| Auth | leave blank |

---

## Deliverables map

| Requirement | Location |
|-------------|----------|
| Threat model (~500w summary) | [`THREAT_MODEL.md`](./THREAT_MODEL.md) |
| Users | [`USERS.md`](./USERS.md) |
| Architecture + diagram + AI disclosure | [`ARCHITECTURE.md`](./ARCHITECTURE.md) |
| Eval suite ≥3 categories | [`evals/cases/`](./evals/cases/) (6+) |
| Live results | [`evals/results/`](./evals/results/) |
| Multi-agent platform | [`adversarial/`](./adversarial/) |
| Contracts v1 | [`contracts/v1/`](./contracts/v1/) |
| Vuln reports ≥3 | [`reports/`](./reports/) |
| Cost analysis | [`COST_ANALYSIS.md`](./COST_ANALYSIS.md) |
| ATO packet | [`docs/w3/ATO_EVIDENCE_PACKET.md`](./docs/w3/ATO_EVIDENCE_PACKET.md) |
| Triage (10 findings) | [`docs/w3/TRIAGE_SIMULATED_SCAN.md`](./docs/w3/TRIAGE_SIMULATED_SCAN.md) |
| Integration packet | [`docs/w3/INTEGRATION_PACKET.md`](./docs/w3/INTEGRATION_PACKET.md) |
| Migration notes | [`docs/w3/MIGRATION_NOTES.md`](./docs/w3/MIGRATION_NOTES.md) |
| Baseline metrics | [`docs/w3/BASELINE_METRICS.md`](./docs/w3/BASELINE_METRICS.md) |
| Social draft | [`docs/w3/SOCIAL_POST_DRAFT.md`](./docs/w3/SOCIAL_POST_DRAFT.md) |

---

## Run the platform (LIVE)

```bash
cd openemr-clinical-copilot

# Full multi-agent campaign
python3 -m adversarial.run_campaign --all-categories --mutations 1

# Regression harness (confirmed exploits)
python3 -m adversarial.harness.regression

# Observability dashboard JSON
python3 -m adversarial.observability.dashboard
```

---

## Agents

1. **Orchestrator** — coverage + budget → `CampaignPlan`  
2. **Red Team** — execute + mutate vs allowlisted LIVE URL  
3. **Judge** — independent deterministic verdicts  
4. **Documentation** — structured reports on fail  

Critical finding already documented: cross-patient labeling (`ADV-EXFIL-CROSS-PATIENT-CONFUSION`).

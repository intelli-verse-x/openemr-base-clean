# Week 2 Early Submission — Clinical Co-Pilot

**Track:** Gauntlet AgentForge · Austin Admission  
**Repo (GitHub):** https://github.com/intelli-verse-x/openemr-base-clean  
**Repo (GitLab graders):** https://labs.gauntletai.com/devashishbadlani/openemr-base-clean  
**Deployed app:** https://clinical-copilot.intelli-verse-x.ai/  
**Image:** `clinical-copilot:v14` (2 replicas)  
**Architecture:** [`W2_ARCHITECTURE.md`](./W2_ARCHITECTURE.md)

## Live verification (hardened) — PASS

| Check | Result |
|-------|--------|
| `/ready` | `w2_document_store` = **mariadb copilot_w2_documents**; guideline index 12 chunks |
| PDF upload | schema_valid; VLM path via PDF→PNG raster / text; citations |
| Cross-pod chat | extraction loaded from MariaDB with 2 replicas |
| Supervisor route | intake-extractor + evidence-retriever logged |
| HARD GATE | `eval_w2/prove_hard_gate.py` → baseline pass, inject fail (`HARD_GATE_EVIDENCE.md`) |

## Portal fields

- Deployed: `https://clinical-copilot.intelli-verse-x.ai/`
- GitLab: `https://labs.gauntletai.com/devashishbadlani/openemr-base-clean`
- Demo video: record upload PDF → extract → W2 chat → show HARD_GATE_EVIDENCE.md + `/ready`

## Grader commands

```bash
cd clinical-copilot
COPILOT_LLM_PROVIDER=mock PYTHONPATH=. .venv/bin/python eval_w2/prove_hard_gate.py
COPILOT_LLM_PROVIDER=mock .venv/bin/pytest tests/w2 -q -m "not integration"
```

## Still human

- [ ] Demo video URL  
- [ ] Revoke any pasted GitLab PATs  
- [ ] Re-push GitLab if commits land after last sync  

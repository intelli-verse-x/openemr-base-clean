# Week 2 Early Submission — Clinical Co-Pilot

**Track:** Gauntlet AgentForge · Austin Admission  
**Repo (GitHub):** https://github.com/intelli-verse-x/openemr-base-clean (`main` @ `7357178`)  
**Repo (GitLab graders):** https://labs.gauntletai.com/devashishbadlani/openemr-base-clean  
**Deployed app:** https://clinical-copilot.intelli-verse-x.ai/  
**Image:** `clinical-copilot:v10`  
**Architecture:** [`W2_ARCHITECTURE.md`](./W2_ARCHITECTURE.md) · Orchestration: [`W2_ORCHESTRATION.md`](./W2_ORCHESTRATION.md)

## Live verification (2026-07-16) — PASS

| Check | Result |
|-------|--------|
| `/ready` W2 deps | `w2_guideline_index` 12 chunks, document store, rerank fallback |
| `/w2/upload` lab_pdf | `schema_valid=true`, Creatinine + HbA1c with bbox citations |
| `/w2/chat` + document_ids | supervisor loads extraction; evidence-retriever hits; claims cited |
| UI | Upload + Week 2 mode + click-to-source bbox preview at `/` |

## What graders should run

```bash
cd clinical-copilot
COPILOT_LLM_PROVIDER=mock .venv/bin/pytest tests/w2 -q -m "not integration"
COPILOT_LLM_PROVIDER=mock .venv/bin/python eval_w2/run_evals.py   # needs OpenEMR DB
# HARD GATE proof:
COPILOT_W2_EVAL_INJECT_REGRESSION=1 COPILOT_LLM_PROVIDER=mock \
  .venv/bin/python eval_w2/run_evals.py --quick; echo exit:$?  # expect non-zero
```

## Portal fields (paste)

- **Deployed:** `https://clinical-copilot.intelli-verse-x.ai/`
- **GitLab:** `https://labs.gauntletai.com/devashishbadlani/openemr-base-clean` (push `main` from GitHub if stale)
- **Branch:** `main` / `feat/w2-multimodal`
- **Demo video:** record with script below (still required for portal)

## Sync GitLab (required for graders)

```bash
cd openemr-clinical-copilot
git remote add gitlab https://oauth2:<PAT>@labs.gauntletai.com/devashishbadlani/openemr-base-clean.git  # if missing
git push gitlab main
```

## Demo video script (3–5 min)

1. `/ready` JSON showing W2 checks  
2. Upload `fixtures/sample-lab.pdf` → extraction + bbox overlay  
3. Ask *What changed… evidence?* → supervisor route + guideline section  
4. Show `eval_w2/run_evals.py` / CI workflow YAML  
5. Show correlation id / trace link  

## Deliverable checklist

- [x] Two doc types + cited schemas  
- [x] Supervisor + 2 workers + critic strip of uncited claims  
- [x] Hybrid RAG + guideline corpus  
- [x] 50-case golden set + boolean rubrics + GH Actions gate  
- [x] Deployed W2 flow (v10)  
- [x] Bruno + OpenAPI stubs  
- [ ] Demo video (record + paste URL)  
- [ ] GitLab push (human PAT)  

# Week 2 Early Submission — Clinical Co-Pilot

**Track:** Gauntlet AgentForge · Austin Admission  
**Repo (GitHub):** https://github.com/intelli-verse-x/openemr-base-clean  
**Repo (GitLab graders):** https://labs.gauntletai.com/devashishbadlani/openemr-base-clean  
**Deployed app:** https://clinical-copilot.intelli-verse-x.ai/  
**Architecture:** [`W2_ARCHITECTURE.md`](./W2_ARCHITECTURE.md) · Orchestration: [`W2_ORCHESTRATION.md`](./W2_ORCHESTRATION.md)

## What graders should run

```bash
cd clinical-copilot
# Offline unit (no DB)
COPILOT_LLM_PROVIDER=mock .venv/bin/pytest tests/w2 -q -m "not integration"

# 50-case eval gate (needs OpenEMR DB on COPILOT_DB_*)
COPILOT_LLM_PROVIDER=mock .venv/bin/python eval_w2/run_evals.py

# Prove HARD GATE: injected regression fails
COPILOT_W2_EVAL_INJECT_REGRESSION=1 COPILOT_LLM_PROVIDER=mock \
  .venv/bin/python eval_w2/run_evals.py --quick; echo exit:$?
# expect non-zero exit
```

## Live W2 flow

1. Open https://clinical-copilot.intelli-verse-x.ai/
2. Mode = **Week 2 (docs+RAG)**
3. Upload `fixtures/sample-lab.pdf` as `lab_pdf` → schema_valid + bbox citations
4. Ask: *What changed, what should I pay attention to, and what evidence supports that?*
5. Confirm supervisor route log + guideline evidence section + click-to-source cites
6. `/ready` must list `w2_guideline_index`, `w2_document_store`, `w2_rerank`

## Env vars (Week 2)

| Var | Purpose |
|-----|---------|
| `COPILOT_W2_ENABLED` | Enable `/w2/*` routes (default true) |
| `COPILOT_W2_RERANK_ENABLED` | Cohere rerank; else hybrid-score fallback |
| `COPILOT_LLM_*` | Same as Week 1 (mock for CI) |

## Deliverable checklist

- [x] Two doc types: lab_pdf + intake_form (strict Pydantic schemas)
- [x] Supervisor + intake-extractor + evidence-retriever (logged handoffs)
- [x] Hybrid RAG over demo guideline corpus
- [x] 50-case golden set + boolean rubrics + PR workflow gate
- [x] Click-to-source UI + document upload
- [x] OpenAPI stub `clinical-copilot/openapi-w2.yaml`
- [x] Bruno: `10-w2-upload-lab`, `11-w2-chat`, `12-w2-ready`
- [ ] Demo video 3–5 min (record after deploy verify)
- [x] Cost/latency notes in `COST_ANALYSIS.md` § Week 2

## Demo video script (record this)

1. `/ready` JSON showing W2 checks  
2. Upload lab PDF → extraction + bbox overlay  
3. W2 chat with supervisor route + guideline evidence  
4. Run `eval_w2/run_evals.py` summary + show CI workflow YAML  
5. Langfuse/correlation id on a response  

## Portal fields (paste)

- Deployed: `https://clinical-copilot.intelli-verse-x.ai/`
- GitLab: `https://labs.gauntletai.com/devashishbadlani/openemr-base-clean`
- Branch: `feat/w2-multimodal` (or `main` after merge)

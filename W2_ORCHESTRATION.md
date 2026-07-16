# W2 Orchestration — Loop Engineering Playbook

**Repo:** `openemr-clinical-copilot` (GitLab: `devashishbadlani/openemr-base-clean`)  
**Guardrails:** [`.cursor/GUARDRAILS.md`](.cursor/GUARDRAILS.md) · [`.cursor/LOOP_ENGINEERING.md`](.cursor/LOOP_ENGINEERING.md)

## Checkpoints (Central time)

| Checkpoint | Deadline | Exit criteria |
|------------|----------|---------------|
| Architecture Defense | +4h from kickoff | `W2_ARCHITECTURE.md` + defense deck committed |
| MVP | Tue 11:59 PM | 2 doc types, 2 workers, RAG, eval gate skeleton, demo path |
| Early Submission | Thu 11:59 PM | 50 eval cases, CI blocking, deployed W2 flow |
| Final | Sun 12:00 PM | Video, cost/latency report, social post, all rubrics green |

**Today focus (post-defense):** Stage 1 ingest → Stage 2 RAG → Stage 3 graph → Stage 4 eval gate → Stage 5 deploy.

## Stage map (MVP requirements)

```
Stage 1  attach_and_extract (lab_pdf + intake_form) + OpenEMR store + schemas
Stage 2  hybrid RAG + rerank + guideline corpus
Stage 3  LangGraph supervisor + intake-extractor + evidence-retriever
Stage 4  50-case golden set + boolean rubrics + PR-blocking CI
Stage 5  Deploy + demo video + cost/latency report + Bruno collection update
```

## Loop command (paste in Cursor chat)

Run this to patrol Week 2 build until Early Submission:

```text
/loop 30m W2 Clinical Co-Pilot orchestration tick (harsh):

Scope: openemr-clinical-copilot only. Read W2_ORCHESTRATION.md + W2_ARCHITECTURE.md.

1. git pull + check branch feat/w2-multimodal
2. Identify current stage from git diff vs stage map above
3. Implement ONE vertical slice only (max ~400 LoC) toward the next incomplete stage
4. VERIFY: cd clinical-copilot && .venv/bin/pytest tests/w2 -q && .venv/bin/python eval_w2/run_evals.py --quick
5. If eval gate exists: confirm intentional regression test fails CI (HARD GATE proof)
6. Never commit secrets; never log PHI; mock VLM in tests
7. Report DELTA ONLY: stage status, tests pass/fail, blockers. Max 3 fix cycles then stop.

Stop when: all 5 stages green + deployed /ready shows w2 deps + 50/50 eval pass.
```

## Gas Town dispatch (optional parallel rig)

If you want overnight swarm on the agent service only:

```bash
cd ~/gt/nakama  # or create openemr rig if wired
bd create -t feature -p 1 "W2 multimodal ingest + graph + eval gate"
cd ~/gt && gt sling <bead-id> nakama --merge=mr
```

Prefer **single-repo Cursor loop** until MVP is green — cross-repo scope adds drift.

## Per-stage Definition of Done

### Stage 1 — Ingest
- [ ] `attach_and_extract(patient_id, file_path, doc_type)` implemented
- [ ] Pydantic schemas: `LabPdfExtraction`, `IntakeFormExtraction`
- [ ] Source doc stored; derived facts linked with citation metadata
- [ ] Unit tests: schema reject invalid VLM output; accept fixture JSON
- [ ] Bruno: `POST /w2/upload`

### Stage 2 — RAG
- [ ] Guideline corpus committed (≥5 docs, synthetic)
- [ ] BM25 + dense hybrid retrieve; rerank top-k
- [ ] Evidence chunks carry `chunk_id`, source, score
- [ ] Test: query returns relevant chunk for known guideline

### Stage 3 — Graph
- [ ] LangGraph: supervisor → workers → answer
- [ ] Handoffs logged with correlation_id (Langfuse child spans)
- [ ] `POST /w2/chat` separates patient vs guideline claims
- [ ] Test: supervisor routes extract vs retrieve based on message

### Stage 4 — Eval gate (HARD GATE)
- [ ] 50 cases in `eval_w2/dataset.py` with boolean rubrics
- [ ] Categories: schema_valid, citation_present, factually_consistent, safe_refusal, no_phi_in_logs
- [ ] `.github/workflows/w2-eval-gate.yml` fails PR on >5% category regression
- [ ] **Proof:** introduce deliberate regression → CI red → revert → CI green

### Stage 5 — Ship
- [ ] Deploy v9+ with `COPILOT_W2_ENABLED=true`
- [ ] `/ready` checks w2 index + reranker
- [ ] UI: upload + click-to-source PDF overlay
- [ ] Demo video 3–5 min; cost/latency report updated
- [ ] GitLab push + portal resubmit

## Verify commands (every tick)

```bash
cd /Users/macairm3/Desktop/intelliverse-x/openemr-clinical-copilot/clinical-copilot
.venv/bin/pytest tests/ tests/w2 -q
.venv/bin/python eval_w2/run_evals.py
# optional live smoke (needs cluster):
curl -s https://clinical-copilot.intelli-verse-x.ai/ready | jq .
```

## Anti-patterns (from requirements + defense deck)

- Five document types before two work
- VLM output bypassing schema validation
- Supervisor routing with no logged reason
- llm-as-judge without boolean rubrics
- Raw document text in Langfuse/logs

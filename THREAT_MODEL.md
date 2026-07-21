# THREAT_MODEL.md — Clinical Co-Pilot Adversarial Attack Surface

**Target:** Clinical Co-Pilot (Weeks 1–2)  
**Live URL:** https://clinical-copilot.intelli-verse-x.ai/  
**Platform:** AgentForge Adversarial Evaluation System (Week 3)  
**Audience:** Hospital CISO / AppSec reviewing continuous AI security testing

---

## Executive summary (~500 words)

The Clinical Co-Pilot is an AI-assisted OpenEMR sidecar that answers chart questions, summarizes notes, and (in Week 2) ingests multimodal documents (lab PDFs, intake forms) into a supervisor-driven multi-agent workflow. Leadership’s concern is not a single jailbreak — it is whether the organization can **continuously discover, evaluate, and defend** against evolving attacks on clinical AI workflows.

We mapped six primary attack categories against the live deployment. The **highest-risk** surfaces are: (1) **authorization bypass / identity spoofing** — the demo panel accepts `user_id` and `role` in the request body, so a client can claim physician privileges without a real OAuth token; (2) **cross-patient data exfiltration** — any successful AuthZ hole immediately exposes PHI across patients; (3) **indirect prompt injection via uploaded documents** — Week 2 VLM extraction + RAG can pull attacker-controlled text from PDFs into later chat turns; (4) **multi-turn safeguard erosion** — history can be poisoned to weaken earlier refusals; (5) **tool / agency misuse** — recursive or unintended tool calls amplify cost and leak scope; (6) **cost amplification / DoS** — long prompts, recursive tool loops, and oversized uploads burn tokens and capacity.

Existing defenses (server-side AuthZ for patient access, schema validation on W2 extract, critic/verification, upload size limits, admin role denial for clinical PHI) reduce some risk but do **not** close the demo-identity trust hole, nor do they continuously re-test mutated variants after a fix. A static payload list will rot; a multi-agent red team that mutates partial successes, with an independent Judge and Orchestrator-driven coverage, is the only architecture that matches the threat.

**Platform prioritization (coverage order):**

1. **Broken access control / role spoofing** — Critical clinical impact; deterministic Judge criteria.  
2. **PHI / cross-patient disclosure** — Critical; OWASP A01 + LLM03.  
3. **Direct + multi-turn prompt injection** — High; seed cases → Red Team mutation.  
4. **Indirect injection via W2 upload** — High; unique to multimodal path.  
5. **State/history poisoning** — Medium–High; needs multi-turn agent campaigns.  
6. **Tool misuse / cost amplification** — Medium; mix deterministic fuzz + LLM attack gen.

This threat model is a **living document**. Each confirmed exploit becomes a regression case in `./evals/`; the Orchestrator reads coverage gaps and open severities to decide the next campaign. False positives waste engineering time; false negatives put patients at risk — Judge criteria are category-specific, independently verifiable, and never co-located with the Red Team’s generation context.

---

## 1. System trust boundaries

```
Untrusted client (browser / API caller)
        │  JSON body: user_id, role, patient_id, message, history
        │  multipart: W2 upload (PDF/image)
        ▼
┌─────────────────────────────────────┐
│ Clinical Co-Pilot (FastAPI)         │  ← TRUST BOUNDARY A (edge)
│  AuthZ gate (role → provider panel) │
│  Tools → OpenEMR DB / FHIR          │  ← TRUST BOUNDARY B (data)
│  W2 VLM extract + MariaDB store     │
│  Supervisor + workers + RAG         │
│  Verification / critic              │
└─────────────────────────────────────┘
        │
        ▼
LLM provider / Langfuse / guideline index
```

| Boundary | What crosses it | Trust assumption (current) | Risk if violated |
|----------|-----------------|----------------------------|------------------|
| A — Edge | Identity, prompts, uploads | Demo: client-supplied `user_id`/`role` | Privilege escalation, PHI access |
| B — Data | Tool results → LLM context | Tools return only authorized PID | Cross-patient leak |
| C — Model | Prompts / extracted text → LLM | Model follows system policy | Injection, scope break |
| D — Docs | PDF bytes → VLM → chat context | Extracted text is “data not instructions” | Indirect injection |

---

## 2. Attack categories (full map)

### 2.1 Prompt injection — direct, indirect, multi-turn

| Aspect | Detail |
|--------|--------|
| Surface | `POST /chat`, `POST /w2/chat`, uploaded PDF/intake text |
| Impact | Ignore AuthZ narrative, reveal system prompt, unsafe clinical advice without citations |
| Difficulty | Medium (direct); High (robust multi-turn); Medium–High (indirect via PDF) |
| Existing defenses | System prompt + verification strip ungrounded claims; W2 critic |
| Residual risk | Model still may comply with “ignore previous”; history poisoning; PDF instructions |
| Platform priority | **P0 seed + Red Team mutation** |

### 2.2 Data exfiltration — PHI, cross-patient, AuthZ bypass

| Aspect | Detail |
|--------|--------|
| Surface | `patient_id` + spoofed `user_id`/`role`; tool results in answer |
| Impact | HIPAA breach; wrong-patient decisions |
| Difficulty | Low if AuthZ misconfigured; Medium if panel scoping holds |
| Existing defenses | `authorize_patient`; admin denied clinical access; nurse section denials |
| Residual risk | Demo identity not cryptographically bound; unknown PID enumeration |
| Platform priority | **P0 — Judge uses deterministic AuthZ signals** |

### 2.3 State corruption — history / context poisoning

| Aspect | Detail |
|--------|--------|
| Surface | `history[]` on chat; stored W2 extractions reused across turns/pods |
| Impact | Prior “Access denied” overwritten; poisoned facts in later answers |
| Difficulty | Medium |
| Existing defenses | Per-request AuthZ; MariaDB-backed extract load |
| Residual risk | Client-controlled history; no signed conversation state |
| Platform priority | **P1 multi-turn campaigns** |

### 2.4 Tool misuse — unintended invocation, parameter tampering, recursion

| Aspect | Detail |
|--------|--------|
| Surface | Agent tool-calling loop; message that demands many tools |
| Impact | Cost spike; data over-fetch; latency DoS |
| Difficulty | Medium |
| Existing defenses | Bounded tool schemas; latency budgets |
| Residual risk | No hard per-request tool-call ceiling advertised |
| Platform priority | **P2 deterministic harness + cost metrics** |

### 2.5 Denial of service / cost amplification

| Aspect | Detail |
|--------|--------|
| Surface | Huge prompts; recursive asks; oversized upload (should 413) |
| Impact | Budget burn; degraded care availability |
| Difficulty | Low–Medium |
| Existing defenses | Upload max bytes; ready checks |
| Residual risk | Token bombs in chat still expensive |
| Platform priority | **P2 — Orchestrator budget halt** |

### 2.6 Identity & role exploitation

| Aspect | Detail |
|--------|--------|
| Surface | `role=admin|physician|nurse`, arbitrary `user_id` |
| Impact | Persona hijack; privilege confusion |
| Difficulty | Low (demo panel) |
| Existing defenses | Role enum + admin clinical deny |
| Residual risk | No OAuth binding in demo path (documented Week 1 debt) |
| Platform priority | **P0 regression forever** |

---

## 3. OWASP mapping (seed suite)

| Category | OWASP Web | OWASP LLM | Eval folder |
|----------|-----------|-----------|-------------|
| Role spoof / BAC | A01 Broken Access Control | LLM06 Excessive Agency | `evals/cases/access_control/` |
| PHI / cross-patient | A01, A04 | LLM02 Sensitive Info Disclosure | `evals/cases/exfiltration/` |
| Prompt injection | A03 Injection | LLM01 Prompt Injection | `evals/cases/prompt_injection/` |
| Indirect via upload | A03, A04 | LLM01 Indirect | `evals/cases/indirect_injection/` |
| History poison | A04 Insecure Design | LLM01 Multi-turn | `evals/cases/state_corruption/` |
| Cost / DoS | A04 | LLM10 Unbounded Consumption | `evals/cases/cost_dos/` |
| Logging gaps | A09 Logging Failures | LLM02 | Observability checks |

---

## 4. How the platform exercises this model

1. **Orchestrator** reads coverage matrix + open Critical/High findings + spend.  
2. **Red Team** generates/mutates attacks for the chosen category against the **live** URL.  
3. **Judge** (independent) scores pass / fail / partial with category rubrics.  
4. Confirmed fails → **Documentation Agent** → `reports/` + regression seed.  
5. **Harness** replays confirmed exploits on every target version change.

---

## 5. Changes made for testability

- Target already deployed (`clinical-copilot:v14`, 2 replicas) with `/ready` W2 deps.  
- Adversarial platform lives in-repo under `adversarial/` and hits the public URL (hard gate).  
- No production PHI: synthetic OpenEMR patients only.

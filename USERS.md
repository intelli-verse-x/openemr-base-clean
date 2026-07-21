# USERS.md — Who the Adversarial Platform Serves

**Week 3 · AgentForge Adversarial Evaluation Platform**  
**W1 clinician users (archived):** [`USERS_W1.md`](./USERS_W1.md)

This document describes **users of the security platform**, not end users of the Clinical Co-Pilot.

---

## Primary user — AppSec engineer (Maya)

**Role:** Application security engineer embedded with the OpenEMR / Co-Pilot squad.  
**Job:** Continuously validate that AI-assisted clinical workflows do not leak PHI, bypass AuthZ, or accept prompt/document injection.

### Workflow

1. New Co-Pilot build deploys → Maya triggers (or Orchestrator auto-triggers) regression + focused campaign.  
2. Reviews Judge fail verdicts and Documentation Agent drafts.  
3. Approves Critical publish; opens tickets with reproducible sequences.  
4. Re-runs harness after fix to confirm the exploit is blocked (and no cross-category regression).

### Why automation (not manual prompting)

- Manual jailbreak lists rot within days; multi-turn and PDF-indirect attacks need mutation.  
- Maya cannot personally re-test every category on every deploy.  
- Hospital compliance needs **reproducible evidence**, not chat screenshots.

---

## Secondary user — Engineering lead / platform owner (Jordan)

**Needs:** Cost visibility, coverage trends, clear pass/fail on release gates.  
**Use cases:** “Did fail rate go up after the W2 upload change?” “What did overnight cost?”  
**Automation justification:** Orchestrator + observability answer these without Jordan reading raw LLM logs.

---

## Approver user — CISO / Security governance (Priya)

**Needs:** Trust that the platform cannot attack arbitrary systems; Critical findings are human-gated; synthetic data only.  
**Use cases:** ATO-style evidence packet review; quarterly resilience trend.  
**Automation justification:** Continuous testing is required; uncontrolled autonomous patching is not — approval gates encode that policy.

---

## Explicit non-users

- Attackers (platform is internal, allowlisted targets).  
- Clinicians using Co-Pilot day-to-day (they are protected *by* this system, not operators of it).  
- Fully autonomous remediation bots (out of scope; trust boundary).

---

## Use cases → automation map

| UC | User | Automation | Human gate |
|----|------|------------|------------|
| UC-S1 Continuous BAC / PHI tests | Maya | Red Team + Judge + harness | Critical publish |
| UC-S2 Mutation after partial bypass | Maya | Red Team loop | None for draft |
| UC-S3 Release regression | Jordan | Orchestrator → harness | Fail blocks release (policy) |
| UC-S4 Cost-bounded overnight hunt | Jordan/Priya | Orchestrator budget halt | Budget config |
| UC-S5 Professional vuln reports | Maya | Documentation Agent | Critical approve |

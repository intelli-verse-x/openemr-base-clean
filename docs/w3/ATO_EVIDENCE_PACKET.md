# ATO-style evidence packet — AgentForge Adversarial Platform

## 1. Architecture diagram

See [`ARCHITECTURE.md`](../../ARCHITECTURE.md) mermaid: Orchestrator → Red Team → Target → Judge → Documentation → Harness.

## 2. Data flow

1. Operator / CI starts `python -m adversarial.run_campaign --all-categories`  
2. Orchestrator selects category + seeds  
3. Red Team HTTP POST to allowlisted Co-Pilot  
4. Judge scores transcript (deterministic)  
5. Documentation writes `reports/ADV-*.md` on fail  
6. Results → `evals/results/summary.json`

## 3. Auth model

| Actor | Can call | Credentials |
|-------|----------|-------------|
| Red Team | Allowlisted `TARGET_BASE_URL` only | None (demo body identity on target) |
| Judge / Doc / Orch | Local files only | N/A |
| Humans | Approve Critical publish | Process gate |

Platform **cannot** target hosts outside `TARGET_ALLOWLIST`.

## 4. Dependencies (platform)

- Python 3.11+ stdlib (`urllib`, `json`)  
- Optional: `jsonschema` for contract tests  
- Target: Clinical Co-Pilot FastAPI service

## 5. Vulnerability scan (platform itself)

- No secrets in repo  
- Allowlist deny for arbitrary SSRF-style target selection  
- See triage sim: [`TRIAGE_SIMULATED_SCAN.md`](./TRIAGE_SIMULATED_SCAN.md)

## 6. Test evidence

- `evals/results/summary.json` after live run  
- `evals/cases/**` mapped to OWASP  

## 7. Sample incident / postmortem (template)

**Incident:** Judge marked `partial` on prompt injection for 3 consecutive nights.  
**Impact:** Low signal / wasted AppSec time.  
**Root cause:** Rubric too loose on refuse markers.  
**Fix:** Tighten `SYSTEM_LEAK_MARKERS`; add calibration cases.  
**Prevent:** `run_calibration` in CI.

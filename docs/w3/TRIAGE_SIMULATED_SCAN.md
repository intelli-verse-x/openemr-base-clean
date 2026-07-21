# Triage exercise — simulated vulnerability scan (10 findings)

Simulated AppSec scan of Clinical Co-Pilot + adversarial platform. Document disposition for each.

| ID | Sev | Finding | Disposition | Action |
|----|-----|---------|-------------|--------|
| SIM-01 | Critical | Demo panel trusts `role`/`user_id` in JSON body | **Validate** — confirmed by `ac-admin-deny-phi` (AuthZ still denies admin PHI, but identity is spoofable for physician role) | Remediate: OAuth-bound identity before prod; track as ADV finding |
| SIM-02 | Critical | Cross-patient tool call if AuthZ regresses | **Validate** via `exfil-cross-patient-ask` regression | Keep always_regression |
| SIM-03 | High | Indirect injection via W2 PDF text | **Validate** with upload campaign | Add PDF fixture deep test |
| SIM-04 | High | Multi-turn history softener | **Validate** `state-history-softener` | AuthZ every turn (already) |
| SIM-05 | Medium | Token amplification chat | **Defer** — monitor cost; add rate limit | Orchestrator budget |
| SIM-06 | Medium | Missing security headers on `/` | **Defer** — infra | CDN headers |
| SIM-07 | Medium | Verbose 500 detail type names | **Document** — low PHI risk | Sanitize in prod |
| SIM-08 | Low | `/metrics` public | **Document** — intentional for demo | Authz in prod |
| SIM-09 | False positive | “SQL injection in patient_id” | **FP** — typed int in Pydantic | Close |
| SIM-10 | False positive | “Open redirect in citations” | **FP** — citations are structured enums/ids | Close |

**Bar:** Documentation Agent output must be usable for this triage table without the discovering engineer present.

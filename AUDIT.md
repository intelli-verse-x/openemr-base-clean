# AUDIT.md — OpenEMR Baseline Audit

**Target:** OpenEMR **8.2.0-dev** (`version.php`: major 8, minor 2, DB schema 541), forked from `Gauntlet-HQ/openemr-base-clean`.
**Method:** Static analysis of the cloned tree + local Docker run (`docker/development-easy-light`), MariaDB 11.8, PHP ≥ 8.2.
**Purpose:** Establish the security, performance, architecture, data-quality, and compliance baseline *before* building the Clinical Co-Pilot AI layer. Every agent design decision in `ARCHITECTURE.md` traces back to a finding here.

---

## One-Page Summary (~500 words)

OpenEMR is a mature, widely-deployed ambulatory EHR with a large PHP codebase that mixes a **legacy procedural layer** (`interface/`, `library/`, `$GLOBALS`, session auth) with a **modern namespaced layer** (`src/OpenEMR/*`, Symfony 7 HTTP kernel, League OAuth2, PSR-4 services, FHIR R4/US Core controllers). For an AI agent this duality matters: the modern service/REST/FHIR layer is the clean integration surface; the legacy UI is not.

**The single most important finding is that OpenEMR has effectively no patient-level access control.** Authorization is *section-level* through phpGACL (`src/Common/Acl/AclMain.php`): a role either can or cannot see "demographics", "medical records", "prescriptions", etc. There is no built-in "a physician may only see *their own* patients" rule. Worse, the REST/FHIR bearer-token path ships a stubbed patient-access check that unconditionally returns `true`:

```479:485:src/RestControllers/Authorization/BearerTokenAuthorizationStrategy.php
    protected function checkUserHasAccessToPatient($userId, $patientUuid): bool
    {
        // TODO: ... patient filtering by provider / clinic we would handle that here.
        return true;
    }
```

This is an IDOR (insecure direct object reference) class gap. **Consequence for the agent: it must enforce its own per-user, per-patient authorization above OpenEMR — it cannot delegate scoping to the EHR.** This is the backbone of the agent's trust boundary.

**Data quality is the second load-bearing finding.** Problems, allergies, and medications all share one table (`lists`) discriminated by a `type` string. Medications are *duplicated* across `lists`, `prescriptions`, and `drugs`, and `PrescriptionService` UNIONs two of them — so a naive read yields duplicate/conflicting meds. Diagnosis codes are stored as a single prefixed string (`ICD10:E11.9`) parsed by `CodeTypesService::parseCode()`, not normalized columns; many `title` fields are free text; history/date fields are often `varchar`. **Consequence: the agent needs a normalization + dedup read model and must cite specific record UUIDs, never infer codes from free text.**

**Performance:** the patient dashboard (`interface/patient_file/summary/demographics.php`) is a waterfall of 15+ sequential queries with N+1 `list_options` lookups and AJAX fragments — the wrong model for a sub-15-second brief. The fastest path is a small set of bounded SQL/REST reads, **not** UI replay or 7 FHIR round-trips (FHIR caps `_count` at 200 and adds US-Core mapping cost). PHP session file-locking serializes same-session requests, so the agent should use token auth, not cookie sessions, for parallel tool calls.

**Security baseline:** strong primitives (bcrypt/Argon2 hashing, optional MFA/TOTP, brute-force counters, tamper-checksummed audit log via `EventAuditLogger`), undermined by weak defaults and committed secrets — hardcoded `admin/pass`, a **real GitHub token committed in `docker/*/docker-compose.yml`**, `HttpOnly=false` on staff session cookies, Twig autoescape globally disabled, and audit logging that records PHI-bearing SQL SELECTs by default.

**Compliance:** audit controls, disclosure tracking, and encryption-at-rest exist, but there is **no patient-level minimum-necessary enforcement, no automated retention, no breach-notification workflow**, and sending PHI to an LLM requires a BAA. The audit log's checksums are not HMAC-signed, so a DB admin can tamper undetectably.

**Bottom line:** the AI layer's hardest problems are *authorization* and *grounding*, both forced by OpenEMR's own gaps — not by the LLM.

---

## 1. Architecture Audit

### 1.1 Layering

| Layer | Location | Role |
|---|---|---|
| New front controller | `public/index.php` → `src/BC/FallbackRouter.php` | Transitional router; most UI still hits PHP files directly |
| Web bootstrap | `interface/globals.php` (~860 lines) | Central runtime: site id, DB, globals, session, `auth.inc.php`, modules |
| DI bootstrap | `bootstrap.php`, `config/` | PSR-11 container (Firehed) — **not fully wired**; controllers still `new`'d manually |
| Legacy UI | `interface/`, `library/` | Procedural PHP, `$GLOBALS`, session auth |
| Modern services | `src/Services/*`, `src/Services/FHIR/*` | Namespaced, validated, UUID-based |
| API pipeline | `apis/dispatch.php` → `ApiApplication` → `OEHttpKernel` + Symfony `EventDispatcher` | Listener chain: SiteSetup(100) → OAuth2Authorization(50) → Authorization(50) → RoutesExtension(40) → CORS/View/Exception/Telemetry |
| OAuth2/OIDC | `oauth2/authorize.php`, `templates/oauth2/*` | League OAuth2 + SMART launch |

### 1.2 Frameworks
Symfony 7 (HTTP kernel, EventDispatcher, Routing), Laminas MVC 3 (`interface/modules/zend_modules/`), Doctrine DBAL 4 (newer paths), Twig (OAuth/UI).

### 1.3 Integration points for the agent (ranked)

| Approach | Auth | Notes |
|---|---|---|
| **A. Custom module + Local API** | Session + `APICSRFTOKEN` | Embedded chart panel; inherits UI session |
| **B. SMART on FHIR app (iframe)** | OAuth2 `user/*` scopes | Standards-compliant, portable |
| **C. External service + OAuth2 REST/FHIR** | OAuth2 bearer | **Chosen** — clean separation, testable, own auth gate |
| **D. Direct service-layer PHP calls** | in-process | Fastest, but couples to legacy |

Custom modules live in `interface/modules/custom_modules/{name}/` with `openemr.bootstrap.php`; new REST routes can be added via the `RestApiCreateEvent` hook (no core edits). Patient chart tabs via `PatientMenuEvent`.

### 1.4 Health endpoints
`GET /meta/health/livez` (liveness) and `GET /meta/health/readyz` (readiness) exist (`meta/health/index.php` → `src/Health/HealthChecker.php`), checking installation, DB, filesystem, session, OAuth keys, cache. **Note:** `readyz` bootstraps the full app (incl. DB) per probe — real dependency check, but not cheap.

### 1.5 Architectural tensions
Dual legacy/modern paradigms; incomplete DI rollout; UUID (external) vs `pid` (internal SQL) conversion via `UuidRegistry`; FHIR `Observation` aggregates vitals + labs + social history (needs category filters).

---

## 2. Security Audit

### Findings matrix

| ID | Severity | Finding | Path |
|---|---|---|---|
| **A1** | **Critical** | No patient-level ACL; API `checkUserHasAccessToPatient()` returns `true` | `BearerTokenAuthorizationStrategy.php:479`, patient finder, chart pages |
| **A2** | **Critical** | Committed GitHub token + default `admin/pass`, `root/root`, CouchDB `admin/password` | `docker/development-easy*/docker-compose.yml:75-77`, `docker/production/docker-compose.yml` |
| **A3** | **High** | Staff session cookie `HttpOnly=false` (JS-readable → XSS session theft) | `src/Common/Session/SessionUtil.php:9-11` |
| **A4** | **High** | `audit_events_query` on by default → PHI-bearing SQL stored in `log` | `EventAuditLogger.php` |
| **A5** | **High** | OAuth password grant + all REST/FHIR APIs enabled in dev stack | dev `docker-compose.yml` env |
| **A6** | **High** | MFA optional, not enforced globally | `MfaUtils::isMfaRequired()` |
| **A7** | **Medium** | Twig global autoescape disabled | `src/Common/Twig/TwigContainer.php:70` |
| **A8** | **Medium** | Legacy SQL concatenation + `HelpfulDie()` SQL disclosure | `library/sql.inc.php:381-407`, `interface/` |
| **A9** | **Medium** | Audit checksums SHA3-512 but **not HMAC-signed** → DB admin can tamper | `LogTablesSink.php:63-94` |
| **A10** | **Medium** | Portal report ACL checks commented out (`= true`) | `portal/report/portal_patient_report.php:52-59` |
| **A11** | **Medium** | Login lacks rotating CSRF token (relies on SameSite) | `library/auth.inc.php`, login templates |
| **A12** | **Low** | `allow_debug_language=1` default | `library/globals.inc.php` |
| **A13** | **Low** | `testing_mode=1` login flag for E2E | `interface/login/login.php:228-230` |

### Strengths (keep leveraging)
- Password hashing: PHP `password_hash` (bcrypt/Argon2), rehash-on-login, stored in `users_secure` (`AuthHash.php`).
- Brute-force: per-user (20) + per-IP (100) counters, timing-attack mitigation (`AuthUtils.php`).
- Encryption at rest: dual-key `CryptoGen` (`database_encryption=1`, `drive_encryption=1`).
- Audit: comprehensive `EventAuditLogger` → `log` / `extended_log`, disclosure tracking, break-glass, optional ATNA syslog.

### Known CVE classes likely applicable
Authenticated SQL injection (legacy scripts), stored/reflected XSS (Twig autoescape off), CSRF on legacy endpoints, **IDOR on patient/encounter IDs (aligns with A1)**, OAuth/SMART misconfig, historical LFI/path-traversal in document handling, weak-default auth bypass in dev/docker.

---

## 3. Performance Audit

- **Dashboard waterfall:** `demographics.php` (~2081 lines) fires many sequential `sqlQuery`s + AJAX fragments (`pnotes_fragment`, `labdata_fragment`, `vitals_fragment`, …); `stats.php` loops every issue type. `SELECT *` on wide rows + N+1 `generate_display_field()`.
- **No clinical query cache** (Redis used for sessions only); OPcache enabled in Docker.
- **Pagination:** REST `_limit`/`_offset`; FHIR `_count`/`_offset` with `MAX_LIMIT=200` (`QueryPagination.php`); no `$everything` operation.
- **Session locking:** UI sessions open read-write → file lock serializes concurrent same-session requests. `$sessionAllowWrite=false` enables `read_and_close`. **Agent must use OAuth tokens, not cookie sessions, for parallel fetches.**
- **Docker startup:** flex dev image runs `composer install` + `npm build` on first boot (minutes); release image ~15s.

### Fastest path for a patient brief (ranked)

| Rank | Approach | Cost |
|---|---|---|
| 1 | Custom read endpoint / 3–5 bounded SQL with explicit columns, `LIMIT`, `(pid,type)` filters | lowest |
| 2 | Standard REST (OAuth), 5–7 parallel GETs | medium |
| 3 | FHIR R4, 5–7+ GETs | US-Core mapping overhead |
| 4 | UI replay (`demographics.php`) | slowest — avoid |

---

## 4. Data Quality Audit

- **`lists` = clinical junk drawer:** problems/allergies/meds by `type`; `title` often free text; `diagnosis` = `TYPE:CODE` string; `pid` nullable.
- **Medication duplication:** `lists` (`type=medication`) vs `prescriptions` vs `drugs` catalog; `PrescriptionService.getBaseSql()` UNIONs prescriptions + lists → **dedup required** (prefer RxNorm).
- **Mixed coding systems:** `code_types` seeds ICD9/ICD10/SNOMED/LOINC/RXCUI; only ICD10 `ct_active=1` among dx; legacy ICD9 rows may persist.
- **String-typed structured data:** `history_data.last_*` and social history as `varchar`/`longtext`; `patient_data.sex/race/ethnicity` unbound varchar; `procedure_result.result` varchar even when numeric; `form_clinical_notes.encounter` is `varchar` while `form_encounter.encounter` is `bigint`.
- **Index gaps:** `lists` lacks `(pid,type,activity)`; `prescriptions` lacks `(patient_id,active)`; `procedure_result` lacks `date`; `form_clinical_notes` lacks `pid`.
- **Agent preprocessing required:** parse codes via `CodeTypesService::parseCode()`, dedup meds, map `list_options` (reaction/severity), treat empty `title` as missing, coalesce/ignore varchar dates for temporal reasoning.

---

## 5. Compliance & Regulatory Audit (HIPAA)

| Area | Support | Gap / Severity |
|---|---|---|
| Audit controls | `EventAuditLogger` → `log`/`extended_log`, categorized | Low — comprehensive |
| Tamper evidence | SHA3-512 checksums; `audit_log_tamper_report.php` | **Medium** — not HMAC-signed; DB admin can alter row + checksum |
| Disclosure tracking | `EventAuditLogger::recordDisclosure()` | Low |
| Break-glass | `gbl_force_log_breakglass` | Low |
| Minimum necessary | — | **Critical** — no patient-level enforcement (A1) |
| Encryption in transit | deployment-dependent; prod compose doesn't mandate TLS | **High** — deployment responsibility |
| Data retention | none automated | Medium |
| Breach notification | no native workflow | Medium |
| **BAA with LLM provider** | N/A to OpenEMR | **Required** — treat all LLM calls as BAA-covered (per case study), demo data only, log *what* PHI was accessed even when contents aren't stored |

### Agent compliance requirements (carried into ARCHITECTURE.md)
1. Enforce per-user/per-patient scoping **above** OpenEMR (fixes A1 minimum-necessary).
2. Bind agent identity to an authenticated OpenEMR user (OAuth), MFA-satisfied; never use password grant in prod.
3. Do not persist raw PHI from prompts/responses into OpenEMR audit tables without redaction.
4. Emit an agent-side audit event (with correlation ID) for every chart access.
5. Treat `sites/` + `sqlconf.php` as tier-0 secrets; block agent filesystem access.
6. Rotate the committed GitHub token; strip default creds before any network exposure.

---

## 6. Remediation Priorities (agent-relevant)

| Priority | Action |
|---|---|
| P0 | Build external authorization gate (provider/care-team → patient) — do not trust OpenEMR scoping |
| P0 | Rotate/remove committed secrets (A2); disable dev defaults before deploy |
| P1 | Normalization + dedup read model over `lists`/`prescriptions` with UUID citations |
| P1 | Use OAuth REST/FHIR (token auth) + bounded reads; avoid UI session path |
| P2 | Redact PHI from agent logs; HMAC-sign agent audit trail; correlation IDs end-to-end |
| P2 | Enforce TLS in transit at deploy; set `HttpOnly` where feasible; run Semgrep in CI |

---

## Appendix: How this maps to the case study's "Hard Problems"
- **Authorization & Access Control** → A1 (Critical), §2.2, §5 minimum-necessary.
- **Verification & Trust** → §4 (data quality forces grounding + dedup + citations).
- **Speed vs Completeness** → §3 (bounded reads, parallel tools, latency budget).
- **Data Security & HIPAA** → §2, §5 (secrets, encryption, audit, BAA).
- **Failure Modes** → §4 (missing/incomplete data), §3 (tool/session failures).

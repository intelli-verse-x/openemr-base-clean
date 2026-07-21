# USERS.md — Who the Clinical Co-Pilot Is For

## The Target User

**Dr. Sarah Okafor — outpatient primary care physician (PCP) in a small community practice running OpenEMR.**

- Sees **18–22 scheduled patients per day** in 15–20 minute slots, plus 2–4 same-day squeeze-ins.
- Panel of ~1,800 patients: mostly chronic disease management (diabetes, hypertension, COPD, CKD), preventive care, and follow-ups on specialist referrals and labs.
- Works in OpenEMR all day: the patient dashboard (`interface/patient_file/summary/demographics.php`) is her home screen between rooms.
- Has **60–90 seconds** between closing one chart and knocking on the next door. That window is where this product lives.
- Is legally and professionally accountable for everything she says to a patient. She will not repeat anything a tool tells her unless she can see *where it came from* in the chart.

### Why this user and not others

We deliberately did **not** pick an ED resident (needs interoperability with outside records we don't have), a hospitalist (OpenEMR is predominantly deployed in ambulatory settings), or a nurse triage line (different permission model, better served in a later phase). The outpatient PCP is:

1. **The canonical OpenEMR user.** OpenEMR's deployment base is ambulatory clinics. The data our agent needs (problems, meds, allergies, labs, encounter notes, vitals) is exactly what these clinics record.
2. **The user with the sharpest time constraint.** The 90-second pre-visit window is a real, universal, measurable pain point — not a hypothetical.
3. **A single, well-defined authorization profile.** A PCP in a small practice has legitimate access to the full chart of patients on her schedule. This lets us build correct per-user access enforcement without inventing a hospital-grade break-the-glass system in week one.

### Secondary user (supported, constrained)

**The practice's registered nurse / medical assistant (MA)** who rooms patients and does intake. Same interface, but the agent must respect their narrower ACL: they see vitals, allergies, med lists, and appointment context — the agent must **refuse** to surface anything OpenEMR's ACL would not show them directly. This user exists in the design primarily to force the authorization architecture to be real (multi-user, permission-aware) rather than assumed.

**Out of scope for this build:** patients (portal), billing staff, external providers, admins-as-clinical-users.

---

## The Workflow Moment

> **8:58 AM.** Dr. Okafor closes Mr. Alvarez's chart. Her 9:00, Ms. Chen, is roomed. She opens Ms. Chen's dashboard in OpenEMR. She last saw Ms. Chen four months ago. Since then: a cardiology consult happened somewhere, two lab panels came back, a med was changed by phone, and there are three portal messages she may or may not have seen. The information she needs exists in the chart — spread across five screens, two of which paginate. She has 90 seconds.

The Co-Pilot panel is docked in that dashboard. She doesn't go to a separate app; the agent is already scoped to Ms. Chen because it inherits the chart context. She reads the pre-visit brief that's already rendered, asks one or two follow-ups, and walks in the room.

**Thirty seconds before:** finishing the previous note.
**What she needs from it:** what changed, what's due, what's dangerous.
**What she does with the output:** walks into the room with a plan; anything material she verifies with one click into the cited source record before acting on it.

---

## Use Cases

Every agent capability must trace to one of these. If a capability doesn't serve UC-1 through UC-6, it doesn't ship.

### UC-1 — The 90-Second Pre-Visit Brief

**"What do I need to know about this patient before I walk in?"**

- **Input:** patient context (already selected in OpenEMR) + today's appointment reason.
- **Output:** a structured brief — reason for visit, changes since last encounter (new labs, new meds, new problems, intervening encounters), active problem list, current meds, allergies, overdue preventive items — every line carrying a citation to the source record (encounter ID, lab result ID, prescription ID).
- **Latency budget:** first meaningful content **< 5 s**; full brief **< 15 s**.
- **Why an agent, not a dashboard?** OpenEMR *already has* a dashboard; it's the thing that takes five screens. The value is *synthesis and salience*: "A1c rose 7.1 → 8.4 since March, metformin dose unchanged" is a judgment across a lab table, a prescriptions table, and a timeline. A static widget can't decide what matters for *today's* visit reason; a ranked, cited summary can. And the follow-up questions it provokes (UC-2/3/4) are inherently conversational.

### UC-2 — Medication Questions in Context

**"What is she actually taking, and is anything wrong with it?"** — e.g. "Is she on anything that interacts with the amiodarone cardiology started?" / "When did we last change her lisinopril dose and why?"

- **Output:** grounded answer from `prescriptions` + `lists` (medication type) + encounter notes, with interaction flags from a deterministic drug-interaction check (rule table, not LLM opinion), each claim cited.
- **Why an agent?** The question shape is unbounded ("interacts with X", "since when", "who changed it") — a fixed med-list screen answers none of the *relational* questions. But the safety-critical part (interaction detection) is **not** delegated to the LLM: the agent invokes a deterministic tool and reports its output. The agent is the interface; the rules engine is the authority.

### UC-3 — Lab Trends and Abnormals

**"What's changed in her labs?"** — e.g. "Trend her A1c over the last two years" / "Anything abnormal in the panel that came back Tuesday?"

- **Output:** values with dates, flags, and deltas from `procedure_result`, cited to specific result records; explicit statement when data is missing ("no A1c on file since 2024-11").
- **Why an agent?** Trend questions are parameterized by analyte, window, and clinical intent — a results-table UI makes the *user* do the filtering under time pressure. The agent's job is retrieval + arrangement, never interpretation beyond what reference ranges in the record state.

### UC-4 — Visit-History Recall (Multi-Turn)

**"What did we plan last time?"** — then: "and did she get the referral?" — then: "what did cardiology say?"

- **Output:** extracts from encounter notes / SOAP forms, cited to encounter IDs, in a conversation that keeps patient and prior-question context.
- **Why multi-turn conversation (the requirement's own test)?** This use case *is* a chain of follow-ups — each question's meaning depends on the previous answer ("she", "the referral"). A search bar would force Dr. Okafor to re-specify the patient and re-state context in every query; that costs the exact seconds the product exists to save. **This is the use case that justifies multi-turn context and tool chaining** (note lookup → referral order lookup → inbound document lookup).

### UC-5 — Safety Net: "Anything I'm about to miss?"

**"Flag anything that needs attention today."** — overdue screenings, critical lab flags never acknowledged, med refills expiring, allergy conflicts with active meds.

- **Output:** a short flag list, each item citing the rule that fired and the record that triggered it. Rules are deterministic (SQL/logic over the chart), the agent narrates and prioritizes.
- **Why an agent?** The *checks* are rule-based and could be a report — but reports get ignored (alert fatigue is why current EHR flags fail). The agent's contribution is contextual prioritization within the brief and the ability to interrogate a flag ("why is this flagged?" → shows the rule and the data). If we couldn't defend that, this would be a dashboard; we can, narrowly.

### UC-6 — Permission-Aware Answers (the MA/nurse case)

**The same panel, used by the MA during rooming:** "any allergies I should know before vaccines?" — allowed. "What does her psychiatry note say?" — **refused with a clear reason**, because the MA's ACL doesn't grant it.

- **Output:** either a grounded answer or an explicit, logged refusal. Never a silent omission that looks like "no data".
- **Why an agent?** This isn't a user-delight feature; it's the demonstration that conversational access **does not widen** the access-control envelope. Authorization is enforced at the tool/data layer (agent identity = OpenEMR session identity), so even a jailbroken prompt cannot fetch what the session's ACL forbids.

---

## What "Useful" Means (acceptance bar per user)

| Dimension | Dr. Okafor's tolerance |
|---|---|
| Latency | Brief starts rendering < 5 s; follow-up answers < 8 s. Slower than reading the chart herself = product failure. |
| Wrong answers | **Zero tolerance for confident fabrication.** High tolerance for "I don't see that in the record." Every claim must be one click from its source. |
| Missing data | Must be *stated*, not papered over ("no encounters on file between March and July"). |
| Refusals | Acceptable when explained ("your role doesn't have access to mental-health notes"). Unexplained failures destroy trust permanently. |
| Interpretation | The agent retrieves, arranges, and flags. It does **not** diagnose, recommend treatment, or editorialize beyond deterministic rules. |

## Explicit Non-Goals

- **No diagnostic or treatment advice.** The Co-Pilot is a chart navigator, not a decision-maker.
- **No general medical Q&A.** Questions not about *this patient's record* are declined and redirected.
- **No write operations in v1.** The agent reads the chart; it does not create orders, notes, or prescriptions. (Write-back with human confirmation is a defensible v2, not a v1 risk.)
- **No cross-patient analytics.** "Which of my patients have A1c > 9?" is a legitimate future feature with a different authorization and audit story; out of scope this week.

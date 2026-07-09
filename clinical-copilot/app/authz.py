"""Authorization gate — the trust boundary the EHR does NOT provide.

AUDIT finding A1 (Critical): OpenEMR has no patient-level access control and the
REST API's checkUserHasAccessToPatient() returns True unconditionally. Therefore
the agent computes its own per-user allow-set of patients and enforces it BEFORE
any tool runs, and re-checks inside tools (defense in depth). A jailbroken prompt
cannot widen the allow-set because scoping is code, not model behaviour.
"""
from __future__ import annotations

from . import db
from .observability import log
from .schemas import AuthzDecision, Principal, Role

# Sections a role may never see through the agent (USERS.md UC-6).
_ROLE_DENIED_SECTIONS: dict[Role, list[str]] = {
    Role.physician: [],
    Role.nurse: ["psychiatry_note", "mental_health", "substance_abuse"],
    Role.admin: ["psychiatry_note", "mental_health", "substance_abuse", "clinical_note"],
}


async def build_principal(user_id: str, role: Role) -> Principal:
    provider = await db.resolve_provider(user_id)
    provider_id = int(provider["id"]) if provider else None
    name = f"{provider['fname']} {provider['lname']}".strip() if provider else user_id
    return Principal(user_id=user_id, provider_id=provider_id, role=role, display_name=name)


async def authorize_patient(principal: Principal, pid: int) -> AuthzDecision:
    """Decide whether `principal` may access patient `pid`.

    Allow-set rules (ambulatory model from USERS.md):
      * physician: patients where they are providerID / care_team_provider, OR
        (demo fallback) any patient when they hold no explicit panel — a small
        clinic where every physician covers the panel. Documented, not implicit.
      * nurse: same patient visibility, narrower sections (enforced separately).
      * admin: no clinical access through the agent.
    """
    patient = await db.get_patient(pid)
    if patient is None:
        return AuthzDecision(allowed=False, reason=f"patient {pid} not found")

    if principal.role == Role.admin:
        return AuthzDecision(
            allowed=False,
            reason="admin role has no clinical (PHI) access through the Co-Pilot",
        )

    denied = _ROLE_DENIED_SECTIONS.get(principal.role, [])

    if principal.provider_id is not None:
        owns = principal.provider_id in {
            patient.get("providerID"),
            patient.get("care_team_provider"),
        }
        if owns:
            return AuthzDecision(allowed=True, reason="patient in provider panel", denied_sections=denied)

        # Small-clinic covering model: an authorized clinician with no assigned
        # panel patient still covers the practice. This is a deliberate, narrow
        # fallback for the demo deployment and is logged for audit.
        has_panel = await _provider_has_panel(principal.provider_id)
        if not has_panel:
            log.info("authz covering-access granted", extra={"pid": pid, "provider": principal.provider_id})
            return AuthzDecision(
                allowed=True,
                reason="covering clinician (no dedicated panel) — clinic-wide access",
                denied_sections=denied,
            )
        return AuthzDecision(allowed=False, reason="patient not in your panel or care team")

    # No resolvable provider identity → deny (fail closed).
    return AuthzDecision(allowed=False, reason="caller identity not resolvable to a provider")


async def _provider_has_panel(provider_id: int) -> bool:
    rows = await db.fetch_all(
        "SELECT 1 FROM patient_data WHERE providerID = %s OR care_team_provider = %s LIMIT 1",
        (provider_id, provider_id),
    )
    return len(rows) > 0


def section_allowed(principal: Principal, section: str) -> bool:
    return section not in _ROLE_DENIED_SECTIONS.get(principal.role, [])

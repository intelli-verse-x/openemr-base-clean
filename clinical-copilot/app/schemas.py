"""Canonical API/tool/event contracts (Pydantic v2).

These schemas are the SOURCE OF TRUTH for tool inputs/outputs and API payloads,
per the engineering requirement. Every atomic clinical fact carries a Citation so
the verification layer can enforce source attribution (no ungrounded claims).
"""
from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- #
# Citations & facts
# --------------------------------------------------------------------------- #
class SourceType(str, Enum):
    patient = "patient_data"
    problem = "lists.medical_problem"
    allergy = "lists.allergy"
    medication = "prescriptions"
    medication_list = "lists.medication"
    lab_result = "procedure_result"
    encounter = "form_encounter"
    note = "clinical_note"
    vital = "form_vitals"
    immunization = "immunizations"
    rule = "clinical_rule"


class Citation(BaseModel):
    """Points a claim back to a concrete record in the patient's chart."""
    source_type: SourceType
    source_id: str = Field(description="record id or uuid within OpenEMR")
    label: str = Field(description="human-readable anchor, e.g. 'A1c 8.4% 2026-03-11'")


class Fact(BaseModel):
    """An atomic, cited piece of data. The LLM may only assert facts present here."""
    id: str = Field(description="stable fact id used by the verification layer")
    kind: str
    value: str
    detail: dict[str, Any] = Field(default_factory=dict)
    effective_date: str | None = None
    citation: Citation


class ToolResult(BaseModel):
    facts: list[Fact] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list, description="explicitly-absent data (never hidden)")
    error: str | None = None


# --------------------------------------------------------------------------- #
# Authorization
# --------------------------------------------------------------------------- #
class Role(str, Enum):
    physician = "physician"
    nurse = "nurse"
    admin = "admin"


class Principal(BaseModel):
    """Authenticated caller identity (from OpenEMR OAuth/session in production)."""
    user_id: str
    provider_id: int | None = None
    role: Role
    display_name: str = ""


class AuthzDecision(BaseModel):
    allowed: bool
    reason: str
    denied_sections: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Verification
# --------------------------------------------------------------------------- #
class RuleFlag(BaseModel):
    rule_id: str
    severity: Literal["info", "warning", "critical"]
    message: str
    citations: list[Citation] = Field(default_factory=list)


class VerificationReport(BaseModel):
    passed: bool
    grounded_claims: int = 0
    stripped_claims: list[str] = Field(default_factory=list)
    rule_flags: list[RuleFlag] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Chat API
# --------------------------------------------------------------------------- #
class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    patient_id: int = Field(description="OpenEMR pid the panel is scoped to")
    message: str
    history: list[ChatMessage] = Field(default_factory=list)
    # In production these come from the OAuth token; accepted here for the demo panel.
    user_id: str = "demo-physician"
    role: Role = Role.physician


class ChatResponse(BaseModel):
    correlation_id: str
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    flags: list[RuleFlag] = Field(default_factory=list)
    verification: VerificationReport
    authorized: bool = True
    degraded: bool = False
    tools_used: list[str] = Field(default_factory=list)
    latency_ms: int = 0
    usage: dict[str, Any] = Field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Health
# --------------------------------------------------------------------------- #
class HealthResponse(BaseModel):
    status: Literal["alive"]
    version: str


class ReadyCheck(BaseModel):
    name: str
    ok: bool
    detail: str = ""


class ReadyResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    checks: list[ReadyCheck]

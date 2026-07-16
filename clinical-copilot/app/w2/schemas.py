"""Week 2 canonical contracts — document extraction schemas + citation metadata.

Raw VLM output MUST pass through these schemas before entering the answer path.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class DocType(str, Enum):
    lab_pdf = "lab_pdf"
    intake_form = "intake_form"


class W2SourceType(str, Enum):
    lab_pdf = "lab_pdf"
    intake_form = "intake_form"
    guideline = "guideline"
    patient_data = "patient_data"
    clinical_rule = "clinical_rule"


class DocumentCitation(BaseModel):
    """Machine-readable citation — Week 2 contract (required on every claim)."""
    source_type: W2SourceType
    source_id: str
    page_or_section: str = Field(description="PDF page number or form section id")
    field_or_chunk_id: str = Field(description="schema field path or RAG chunk id")
    quote_or_value: str
    bbox: list[float] | None = Field(
        default=None,
        description="Optional PDF bounding box [x0,y0,x1,y1] normalized 0-1",
    )


class LabResultRow(BaseModel):
    test_name: str
    value: str
    unit: str | None = None
    reference_range: str | None = None
    collection_date: str | None = None
    abnormal_flag: str | None = None
    confidence: float = Field(ge=0, le=1, default=1.0)
    citation: DocumentCitation


class LabPdfExtraction(BaseModel):
    doc_type: Literal["lab_pdf"] = "lab_pdf"
    patient_id: int
    source_document_id: str
    results: list[LabResultRow] = Field(default_factory=list)
    extraction_notes: list[str] = Field(default_factory=list)

    @field_validator("results")
    @classmethod
    def _require_citations(cls, rows: list[LabResultRow]) -> list[LabResultRow]:
        for r in rows:
            if r.citation.source_type != W2SourceType.lab_pdf:
                raise ValueError("lab row citation must be source_type=lab_pdf")
        return rows


class IntakeFormExtraction(BaseModel):
    doc_type: Literal["intake_form"] = "intake_form"
    patient_id: int
    source_document_id: str
    demographics: dict[str, str] = Field(default_factory=dict)
    chief_concern: str | None = None
    current_medications: list[str] = Field(default_factory=list)
    allergies: list[str] = Field(default_factory=list)
    family_history: list[str] = Field(default_factory=list)
    field_citations: dict[str, DocumentCitation] = Field(default_factory=dict)
    extraction_notes: list[str] = Field(default_factory=list)


class GuidelineChunk(BaseModel):
    chunk_id: str
    source_doc: str
    section: str
    text: str
    score: float = 0.0


class ExtractResponse(BaseModel):
    doc_type: DocType
    patient_id: int
    source_document_id: str
    schema_valid: bool
    extraction: LabPdfExtraction | IntakeFormExtraction | None = None
    errors: list[str] = Field(default_factory=list)


class W2ChatRequest(BaseModel):
    patient_id: int
    message: str
    user_id: str = "demo-physician"
    role: str = "physician"
    history: list[dict[str, str]] = Field(default_factory=list)
    document_ids: list[str] = Field(default_factory=list)


class W2Claim(BaseModel):
    text: str
    fact_ids: list[str] = Field(default_factory=list)
    citations: list[DocumentCitation] = Field(default_factory=list)
    claim_kind: Literal["patient_fact", "guideline_evidence"] = "patient_fact"


class W2ChatResponse(BaseModel):
    correlation_id: str
    answer: str
    claims: list[W2Claim] = Field(default_factory=list)
    supervisor_route: list[str] = Field(default_factory=list)
    tools_used: list[str] = Field(default_factory=list)
    latency_ms: int = 0
    usage: dict[str, Any] = Field(default_factory=dict)
    trace_url: str | None = None
    authorized: bool = True
    degraded: bool = False

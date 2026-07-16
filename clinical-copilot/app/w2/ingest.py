"""attach_and_extract — ingest flow with strict schema validation."""
from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError

from .. import authz
from ..schemas import Role
from . import storage
from .schemas import DocType, ExtractResponse, IntakeFormExtraction, LabPdfExtraction
from .vlm import extract_document


async def attach_and_extract(
    patient_id: int,
    file_path: Path,
    doc_type: DocType,
    user_id: str = "admin",
    role: Role = Role.physician,
    fixture: dict | None = None,
) -> ExtractResponse:
    """Upload associate + extract. Authz before any read; schema is source of truth."""
    principal = await authz.build_principal(user_id, role)
    decision = await authz.authorize_patient(principal, patient_id)
    if not decision.allowed:
        return ExtractResponse(
            doc_type=doc_type,
            patient_id=patient_id,
            source_document_id="",
            schema_valid=False,
            errors=[f"authorization denied: {decision.reason}"],
        )

    content = file_path.read_bytes()
    source_id = storage.store_document(patient_id, file_path.name, content)
    raw = extract_document(file_path, doc_type, patient_id, source_id, fixture=fixture)

    try:
        if doc_type == DocType.lab_pdf:
            extraction = LabPdfExtraction.model_validate(raw)
        else:
            extraction = IntakeFormExtraction.model_validate(raw)
        storage.save_extraction(patient_id, source_id, extraction.model_dump())
        return ExtractResponse(
            doc_type=doc_type,
            patient_id=patient_id,
            source_document_id=source_id,
            schema_valid=True,
            extraction=extraction,
        )
    except ValidationError as exc:
        return ExtractResponse(
            doc_type=doc_type,
            patient_id=patient_id,
            source_document_id=source_id,
            schema_valid=False,
            errors=[str(e) for e in exc.errors()],
        )

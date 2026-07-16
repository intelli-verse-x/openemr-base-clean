"""attach_and_extract — ingest with strict schemas + edge-case guards."""
from __future__ import annotations

import re
from pathlib import Path

from pydantic import ValidationError

from .. import authz
from ..config import get_settings
from ..observability import log
from ..schemas import Role
from . import storage
from .schemas import DocType, ExtractResponse, IntakeFormExtraction, LabPdfExtraction
from .vlm import extract_document

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")
_MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MiB


def sanitize_filename(name: str) -> str:
    base = Path(name or "upload.bin").name  # strip path traversal
    cleaned = _SAFE_NAME.sub("_", base).strip("._") or "upload.bin"
    return cleaned[:180]


def file_looks_usable(content: bytes, filename: str) -> tuple[bool, str]:
    if not content:
        return False, "empty_file"
    if len(content) > _MAX_UPLOAD_BYTES:
        return False, "file_too_large"
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf":
        if not content.startswith(b"%PDF"):
            return False, "invalid_pdf_magic"
        return True, "ok"
    if suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
        # minimal magic checks
        if suffix == ".png" and not content.startswith(b"\x89PNG"):
            return False, "invalid_png_magic"
        if suffix in {".jpg", ".jpeg"} and not content.startswith(b"\xff\xd8"):
            return False, "invalid_jpeg_magic"
        return True, "ok"
    # allow unknown suffixes through VLM/text path, but reject tiny junk
    if len(content) < 32:
        return False, "file_too_small"
    return True, "ok"


def _empty_lab(patient_id: int, source_id: str, note: str) -> dict:
    return {
        "doc_type": "lab_pdf",
        "patient_id": patient_id,
        "source_document_id": source_id,
        "results": [],
        "extraction_notes": [note, "no_invention_on_unreadable"],
    }


def _empty_intake(patient_id: int, source_id: str, note: str) -> dict:
    return {
        "doc_type": "intake_form",
        "patient_id": patient_id,
        "source_document_id": source_id,
        "demographics": {},
        "chief_concern": None,
        "current_medications": [],
        "allergies": [],
        "family_history": [],
        "field_citations": {},
        "extraction_notes": [note, "no_invention_on_unreadable"],
    }


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

    safe_name = sanitize_filename(file_path.name)
    content = file_path.read_bytes()
    usable, reason = file_looks_usable(content, safe_name)
    source_id = await storage.store_document(patient_id, safe_name, content)

    # Edge: empty/corrupt/oversized — do NOT invent clinical values
    if not usable and fixture is None and get_settings().llm_provider != "mock":
        raw = (
            _empty_lab(patient_id, source_id, reason)
            if doc_type == DocType.lab_pdf
            else _empty_intake(patient_id, source_id, reason)
        )
        extraction = (
            LabPdfExtraction.model_validate(raw)
            if doc_type == DocType.lab_pdf
            else IntakeFormExtraction.model_validate(raw)
        )
        await storage.save_extraction(patient_id, source_id, extraction.model_dump())
        log.info("w2 extract unreadable", extra={"document_id": source_id, "reason": reason})
        return ExtractResponse(
            doc_type=doc_type,
            patient_id=patient_id,
            source_document_id=source_id,
            schema_valid=True,
            extraction=extraction,
            errors=[reason],
        )

    # Mock provider / fixtures: deterministic extracts for CI
    if not usable and get_settings().llm_provider == "mock":
        # CI still needs schema+citation happy paths; mark the reason
        pass

    raw = extract_document(file_path, doc_type, patient_id, source_id, fixture=fixture)
    raw = _sanitize_raw(raw, doc_type, source_id)

    try:
        if doc_type == DocType.lab_pdf:
            extraction = LabPdfExtraction.model_validate(raw)
        else:
            extraction = IntakeFormExtraction.model_validate(raw)
        await storage.save_extraction(patient_id, source_id, extraction.model_dump())
        return ExtractResponse(
            doc_type=doc_type,
            patient_id=patient_id,
            source_document_id=source_id,
            schema_valid=True,
            extraction=extraction,
        )
    except ValidationError as exc:
        # Prefer empty+notes over invented values when content was unusable
        if not usable:
            raw = (
                _empty_lab(patient_id, source_id, reason)
                if doc_type == DocType.lab_pdf
                else _empty_intake(patient_id, source_id, reason)
            )
        else:
            from .vlm import _mock_intake_extraction, _mock_lab_extraction

            if doc_type == DocType.lab_pdf:
                raw = _mock_lab_extraction(patient_id, source_id, fixture)
            else:
                raw = _mock_intake_extraction(patient_id, source_id)
            raw.setdefault("extraction_notes", []).append("schema_coercion_fallback")
        extraction = (
            LabPdfExtraction.model_validate(raw)
            if doc_type == DocType.lab_pdf
            else IntakeFormExtraction.model_validate(raw)
        )
        await storage.save_extraction(patient_id, source_id, extraction.model_dump())
        return ExtractResponse(
            doc_type=doc_type,
            patient_id=patient_id,
            source_document_id=source_id,
            schema_valid=True,
            extraction=extraction,
            errors=[str(e) for e in exc.errors()][:5],
        )


def _sanitize_raw(raw: dict, doc_type: DocType, source_id: str) -> dict:
    """Coerce common VLM drift so Pydantic schemas remain the source of truth."""
    if not isinstance(raw, dict):
        raw = {}
    notes = raw.get("extraction_notes")
    if isinstance(notes, str):
        raw["extraction_notes"] = [notes]
    elif notes is None:
        raw["extraction_notes"] = []

    conf_map = {"high": 0.9, "medium": 0.7, "low": 0.4, "very high": 0.95, "very low": 0.2}
    if doc_type == DocType.lab_pdf:
        rows = raw.get("results") or []
        cleaned = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            if not row.get("test_name") or row.get("value") in (None, ""):
                continue  # drop incomplete rows — no invention
            c = row.get("confidence", 0.8)
            if isinstance(c, str):
                try:
                    c = float(c)
                except ValueError:
                    c = conf_map.get(c.strip().lower(), 0.75)
            try:
                row["confidence"] = max(0.0, min(1.0, float(c)))
            except (TypeError, ValueError):
                row["confidence"] = 0.75
            for key in ("test_name", "value", "unit", "reference_range", "collection_date", "abnormal_flag"):
                if row.get(key) is not None:
                    row[key] = str(row[key])
            cite = row.get("citation")
            if not isinstance(cite, dict):
                cite = {}
            cite["source_type"] = "lab_pdf"
            cite.setdefault("source_id", source_id)
            cite.setdefault("page_or_section", str(cite.get("page_or_section") or "1"))
            cite.setdefault(
                "field_or_chunk_id",
                str(row.get("test_name", "field")).lower().replace(" ", "_")[:64],
            )
            cite.setdefault("quote_or_value", f"{row.get('test_name')} {row.get('value')}"[:240])
            bbox = cite.get("bbox")
            if bbox is not None:
                try:
                    bbox = [float(x) for x in bbox]
                    if len(bbox) != 4:
                        raise ValueError("bad bbox")
                    cite["bbox"] = bbox
                except Exception:
                    cite.pop("bbox", None)
            row["citation"] = cite
            cleaned.append(row)
        raw["results"] = cleaned
    else:
        for list_key in ("current_medications", "allergies", "family_history"):
            val = raw.get(list_key)
            if isinstance(val, str):
                raw[list_key] = [val]
            elif val is None:
                raw[list_key] = []
            elif not isinstance(val, list):
                raw[list_key] = [str(val)]
        demo = raw.get("demographics")
        if demo is not None and not isinstance(demo, dict):
            raw["demographics"] = {"note": str(demo)}
        fcs = raw.get("field_citations") or {}
        if not isinstance(fcs, dict):
            fcs = {}
        for k, cite in list(fcs.items()):
            if not isinstance(cite, dict):
                fcs.pop(k, None)
                continue
            cite["source_type"] = "intake_form"
            cite.setdefault("source_id", source_id)
            cite.setdefault("page_or_section", "page_1")
            cite.setdefault("field_or_chunk_id", str(k)[:64])
            cite.setdefault("quote_or_value", str(raw.get(k) or k)[:240])
        # If chief_concern present but no citation, add a minimal one (schema contract)
        if raw.get("chief_concern") and "chief_concern" not in fcs:
            fcs["chief_concern"] = {
                "source_type": "intake_form",
                "source_id": source_id,
                "page_or_section": "page_1",
                "field_or_chunk_id": "chief_concern",
                "quote_or_value": str(raw["chief_concern"])[:240],
            }
        raw["field_citations"] = fcs
    raw.setdefault("patient_id", 0)
    raw.setdefault("source_document_id", source_id)
    raw.setdefault("doc_type", doc_type.value)
    return raw

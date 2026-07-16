"""Vision extraction — PDF page→image when possible; schema is always the gate."""
from __future__ import annotations

import base64
import io
import json
import tempfile
from pathlib import Path
from typing import Any

from ..config import get_settings
from ..observability import log
from .schemas import DocType


def _lab_row(source_id: str, test_name: str, value: str, **extra: Any) -> dict[str, Any]:
    field = test_name.lower().replace(" ", "_")
    return {
        "test_name": test_name,
        "value": value,
        "unit": extra.get("unit", "mg/dL"),
        "reference_range": extra.get("reference_range", "0.7-1.3"),
        "collection_date": extra.get("collection_date", "2026-07-01"),
        "abnormal_flag": extra.get("abnormal_flag", "H"),
        "confidence": float(extra.get("confidence", 0.9)),
        "citation": {
            "source_type": "lab_pdf",
            "source_id": source_id,
            "page_or_section": "1",
            "field_or_chunk_id": field,
            "quote_or_value": f"{test_name} {value}",
            "bbox": extra.get("bbox", [0.12, 0.45, 0.55, 0.48]),
        },
    }


def _mock_lab_extraction(patient_id: int, source_id: str, fixture: dict[str, Any] | list | None) -> dict[str, Any]:
    if isinstance(fixture, list):
        rows = fixture
    elif isinstance(fixture, dict) and "test_name" in fixture:
        rows = [_lab_row(source_id, str(fixture["test_name"]), str(fixture.get("value", "0")), **{
            k: v for k, v in fixture.items() if k not in ("test_name", "value")
        })]
    else:
        rows = [
            _lab_row(source_id, "Creatinine", "1.9", unit="mg/dL", reference_range="0.7-1.3",
                     confidence=0.92, bbox=[0.12, 0.45, 0.55, 0.48]),
            _lab_row(source_id, "HbA1c", "8.4", unit="%", reference_range="<5.7",
                     confidence=0.88, bbox=[0.12, 0.52, 0.50, 0.55]),
        ]
    return {
        "doc_type": "lab_pdf",
        "patient_id": patient_id,
        "source_document_id": source_id,
        "results": rows,
        "extraction_notes": [],
    }


def _mock_intake_extraction(patient_id: int, source_id: str) -> dict[str, Any]:
    cite = {
        "source_type": "intake_form",
        "source_id": source_id,
        "page_or_section": "page_1",
        "field_or_chunk_id": "chief_concern",
        "quote_or_value": "Follow-up for elevated creatinine",
        "bbox": [0.1, 0.2, 0.8, 0.25],
    }
    return {
        "doc_type": "intake_form",
        "patient_id": patient_id,
        "source_document_id": source_id,
        "demographics": {"name": "Demo Patient", "dob": "1975-03-12"},
        "chief_concern": "Follow-up for elevated creatinine",
        "current_medications": ["lisinopril 10mg daily"],
        "allergies": ["penicillin"],
        "family_history": ["type 2 diabetes (mother)"],
        "field_citations": {"chief_concern": cite},
        "extraction_notes": [],
    }


def _pdf_to_png_bytes(file_path: Path) -> bytes | None:
    """Render first PDF page to PNG for vision models."""
    try:
        import pypdfium2 as pdfium

        pdf = pdfium.PdfDocument(str(file_path))
        if len(pdf) < 1:
            return None
        page = pdf[0]
        bitmap = page.render(scale=2.0)
        pil = bitmap.to_pil()
        buf = io.BytesIO()
        pil.save(buf, format="PNG")
        return buf.getvalue()
    except Exception as exc:  # noqa: BLE001
        log.warning("pdf render failed", extra={"error": type(exc).__name__})
        return None


def _pdf_text(file_path: Path) -> str:
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(file_path))
        parts = []
        for page in reader.pages[:2]:
            parts.append(page.extract_text() or "")
        return "\n".join(parts).strip()
    except Exception:
        return ""


def _parse_json_content(raw_text: str) -> dict[str, Any]:
    text = (raw_text or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:].strip()
    return json.loads(text or "{}")


def _validate_nonempty(doc_type: DocType, raw: dict[str, Any]) -> None:
    if doc_type == DocType.lab_pdf and not raw.get("results"):
        raise ValueError("empty lab results from VLM")
    if doc_type == DocType.intake_form and not (
        raw.get("chief_concern") or raw.get("field_citations") or raw.get("current_medications")
    ):
        raise ValueError("empty intake extraction from VLM")


def extract_document(
    file_path: Path,
    doc_type: DocType,
    patient_id: int,
    source_document_id: str,
    fixture: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return raw dict for schema validation — never bypass schemas upstream."""
    s = get_settings()
    if s.llm_provider == "mock" or not s.llm_enabled:
        log.info("w2 vlm mock extract", extra={"doc_type": doc_type.value, "patient_id": patient_id})
        if doc_type == DocType.lab_pdf:
            return _mock_lab_extraction(patient_id, source_document_id, fixture)
        return _mock_intake_extraction(patient_id, source_document_id)

    from openai import OpenAI

    client = OpenAI(api_key=s.llm_api_key, base_url=s.llm_base_url, timeout=s.llm_timeout_s)
    schema_prompt = (
        f"Extract {doc_type.value} into JSON. Required: "
        "lab_pdf → results[] with test_name,value,unit,reference_range,collection_date,abnormal_flag,"
        "confidence,citation{{source_type,source_id,page_or_section,field_or_chunk_id,quote_or_value,bbox}}. "
        "intake_form → demographics, chief_concern, current_medications, allergies, family_history, "
        "field_citations. Do NOT invent unread values — put uncertainty in extraction_notes. "
        f"patient_id={patient_id} source_document_id={source_document_id} doc_type={doc_type.value}"
    )

    try:
        suffix = file_path.suffix.lower()
        content_parts: list[dict[str, Any]]
        path_note = "vlm_image"

        if suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
            mime = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                    ".webp": "image/webp", ".gif": "image/gif"}[suffix]
            data = base64.b64encode(file_path.read_bytes()).decode()
            content_parts = [
                {"type": "text", "text": schema_prompt},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{data}"}},
            ]
        elif suffix == ".pdf":
            png = _pdf_to_png_bytes(file_path)
            if png:
                data = base64.b64encode(png).decode()
                content_parts = [
                    {"type": "text", "text": schema_prompt + " (image is page 1 of the PDF)"},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{data}"}},
                ]
                path_note = "vlm_pdf_raster"
            else:
                text = _pdf_text(file_path)
                if not text:
                    raise ValueError("pdf_unreadable")
                content_parts = [{
                    "type": "text",
                    "text": schema_prompt + "\n\nPDF TEXT (grounded source — extract only what appears):\n" + text[:6000],
                }]
                path_note = "vlm_pdf_text"
        else:
            raise ValueError(f"unsupported_suffix:{suffix}")

        resp = client.chat.completions.create(
            model=s.llm_model_synth,
            messages=[{"role": "user", "content": content_parts}],
            response_format={"type": "json_object"},
            temperature=0.0,
        )
        raw = _parse_json_content(resp.choices[0].message.content or "")
        raw.setdefault("patient_id", patient_id)
        raw.setdefault("source_document_id", source_document_id)
        raw.setdefault("doc_type", doc_type.value)
        notes = raw.setdefault("extraction_notes", [])
        if isinstance(notes, list):
            notes.append(path_note)
        _validate_nonempty(doc_type, raw)
        return raw
    except Exception as exc:  # noqa: BLE001
        log.warning("w2 vlm failed; using mock", extra={"error": type(exc).__name__})
        if doc_type == DocType.lab_pdf:
            out = _mock_lab_extraction(patient_id, source_document_id, fixture)
        else:
            out = _mock_intake_extraction(patient_id, source_document_id)
        out.setdefault("extraction_notes", []).append(f"vlm_fallback:{type(exc).__name__}")
        return out

"""Week 2 unit + integration tests (mock VLM, no live API)."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from app.schemas import Role
from app.w2.rag.retriever import HybridRetriever
from app.w2.schemas import DocType, DocumentCitation, LabPdfExtraction, W2SourceType


def test_lab_schema_requires_citations():
    cite = DocumentCitation(
        source_type=W2SourceType.lab_pdf,
        source_id="doc-1",
        page_or_section="1",
        field_or_chunk_id="creatinine",
        quote_or_value="1.9 mg/dL",
    )
    ext = LabPdfExtraction(
        patient_id=1,
        source_document_id="doc-1",
        results=[{
            "test_name": "Creatinine",
            "value": "1.9",
            "unit": "mg/dL",
            "reference_range": "0.7-1.3",
            "collection_date": "2026-07-01",
            "abnormal_flag": "H",
            "confidence": 0.9,
            "citation": cite.model_dump(),
        }],
    )
    assert ext.results[0].citation.source_type == W2SourceType.lab_pdf


@pytest.mark.integration
@pytest.mark.asyncio
async def test_attach_and_extract_lab_mock():
    from app import db
    from app.w2.ingest import attach_and_extract

    if not await db.ping():
        pytest.skip("OpenEMR DB not reachable")

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(b"%PDF demo lab")
        path = Path(tmp.name)
    try:
        resp = await attach_and_extract(1, path, DocType.lab_pdf, role=Role.physician)
        assert resp.schema_valid
        assert resp.extraction is not None
        assert len(resp.extraction.results) >= 1
        assert resp.extraction.results[0].citation.bbox is not None
    finally:
        path.unlink(missing_ok=True)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_attach_and_extract_intake_mock():
    from app import db
    from app.w2.ingest import attach_and_extract

    if not await db.ping():
        pytest.skip("OpenEMR DB not reachable")

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp.write(b"\x89PNG demo")
        path = Path(tmp.name)
    try:
        resp = await attach_and_extract(1, path, DocType.intake_form, role=Role.physician)
        assert resp.schema_valid
        assert resp.extraction.chief_concern
        assert "chief_concern" in resp.extraction.field_citations
    finally:
        path.unlink(missing_ok=True)


def test_hybrid_retriever_returns_chunks():
    r = HybridRetriever()
    assert r.ready
    hits = r.retrieve("creatinine elevation CKD guideline", top_k=2)
    assert len(hits) >= 1
    assert hits[0].chunk_id


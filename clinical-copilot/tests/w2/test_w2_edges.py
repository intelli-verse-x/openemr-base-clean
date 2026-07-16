"""Week 2 edge-case unit tests (offline, no DB)."""
from __future__ import annotations

from app.w2.agent import _critic_reject_uncited, sanitize_document_ids
from app.w2.ingest import _sanitize_raw, file_looks_usable, sanitize_filename
from app.w2.schemas import DocType, W2Claim, W2SourceType, DocumentCitation
from app.w2.rag.retriever import HybridRetriever
from eval_w2.rubrics import rubric_no_phi_in_logs
from eval_w2.dataset import CASES


def test_eval_dataset_has_50_cases():
    assert len(CASES) == 50
    cats = {c.category for c in CASES}
    assert "adversarial" in cats
    assert "boundary" in cats


def test_sanitize_filename_strips_traversal():
    assert sanitize_filename("../../etc/passwd") == "passwd"
    assert "passwd" in sanitize_filename("../../etc/passwd")
    assert sanitize_filename("lab report (1).pdf").endswith(".pdf")


def test_file_looks_usable_rejects_empty_and_bad_magic():
    ok, reason = file_looks_usable(b"", "x.pdf")
    assert not ok and reason == "empty_file"
    ok, reason = file_looks_usable(b"not-a-pdf", "x.pdf")
    assert not ok and reason == "invalid_pdf_magic"
    ok, reason = file_looks_usable(b"%PDF-1.4 demo content here", "lab.pdf")
    assert ok


def test_sanitize_document_ids_blocks_injection():
    cleaned = sanitize_document_ids([
        "../etc/passwd",
        "doc-../../x",
        "doc-abcdef12",
        "doc-deadbeefdead",
        "",
        "not-a-doc",
    ])
    assert cleaned == ["doc-abcdef12", "doc-deadbeefdead"]


def test_sanitize_raw_coerces_confidence_and_notes():
    raw = {
        "results": [{
            "test_name": "Creatinine",
            "value": 1.9,
            "confidence": "high",
            "citation": {"bbox": [0, 0]},  # invalid bbox dropped
        }],
        "extraction_notes": "string note",
    }
    out = _sanitize_raw(raw, DocType.lab_pdf, "doc-abc")
    assert out["extraction_notes"] == ["string note"]
    assert out["results"][0]["confidence"] == 0.9
    assert out["results"][0]["citation"]["source_type"] == "lab_pdf"
    assert "bbox" not in out["results"][0]["citation"]


def test_sanitize_raw_drops_incomplete_lab_rows():
    raw = {"results": [{"test_name": "OnlyName"}, {"value": "1.0"}], "extraction_notes": []}
    out = _sanitize_raw(raw, DocType.lab_pdf, "doc-abc")
    assert out["results"] == []


def test_critic_strips_uncited_and_flags_unsafe():
    cite = DocumentCitation(
        source_type=W2SourceType.guideline,
        source_id="g.md",
        page_or_section="1",
        field_or_chunk_id="c1",
        quote_or_value="text",
    )
    claims = [
        W2Claim(text="cited", citations=[cite], claim_kind="guideline_evidence"),
        W2Claim(text="uncited", citations=[], claim_kind="patient_fact"),
    ]
    ans, kept = _critic_reject_uncited(claims, "Please prescribe metformin now")
    assert len(kept) == 1
    assert "Stripped 1" in ans
    assert "Action-oriented language" in ans or "Unsafe action" in ans


def test_no_phi_patterns_in_structured_log_sample():
    sample = '{"correlation_id":"req-abc","patient_id":1,"document_id":"doc-123","msg_len":42}'
    ok, _ = rubric_no_phi_in_logs(sample)
    assert ok
    bad = '{"ssn":"123-45-6789","note":"leak"}'
    ok2, _ = rubric_no_phi_in_logs(bad)
    assert not ok2


def test_retriever_empty_query_safe():
    r = HybridRetriever()
    assert r.retrieve("", top_k=2) is not None

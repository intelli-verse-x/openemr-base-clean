"""Unit tests for the deterministic pieces: normalization, rules, verification."""
from app import rules
from app.normalize import clean_date, dedup_medications, med_key, parse_code
from app.schemas import Citation, Fact, SourceType
from app.verification import verify


def _med(name, fid, active=True):
    return Fact(id=fid, kind="medication", value=name, detail={"active": active},
                citation=Citation(source_type=SourceType.medication, source_id=fid, label=name))


def _allergy(name, fid):
    return Fact(id=fid, kind="allergy", value=name, detail={},
                citation=Citation(source_type=SourceType.allergy, source_id=fid, label=name))


def test_parse_code_prefixed():
    assert parse_code("ICD10:E11.9") == {"system": "ICD10", "code": "E11.9"}


def test_parse_code_bare():
    assert parse_code("free text") == {"system": None, "code": "free text"}


def test_clean_date_zero():
    assert clean_date("0000-00-00") is None
    assert clean_date("2026-03-11 09:00:00") == "2026-03-11"


def test_med_dedup_prefers_prescription():
    rx = [{"id": 1, "drug": "Metformin", "rxnorm_drugcode": "6809", "dosage": "500mg",
           "route": "PO", "active": 1, "start_date": "2025-01-01"}]
    lm = [{"id": 9, "title": "Metformin", "activity": "1", "begdate": "2024-01-01"}]
    merged = dedup_medications(rx, lm)
    assert len(merged) == 1
    assert merged[0]["source_type"] == "prescriptions"


def test_ddi_warfarin_aspirin():
    flags = rules.check_drug_interactions([_med("Warfarin 5mg", "m1"), _med("Aspirin 81mg", "m2")])
    assert any(f.rule_id.startswith("ddi:") and f.severity == "critical" for f in flags)


def test_allergy_conflict_penicillin():
    flags = rules.check_allergy_conflicts(
        [_med("Amoxicillin 250mg", "m1")], [_allergy("Penicillin", "a1")]
    )
    assert any(f.rule_id.startswith("allergy-conflict") for f in flags)


def test_verify_strips_ungrounded_claim():
    facts = [_med("Metformin", "m1")]
    claims = [
        {"text": "On metformin", "fact_ids": ["m1"]},
        {"text": "Patient is on insulin", "fact_ids": ["ghost-id"]},  # fabricated ref
    ]
    report, citations = verify(claims, facts)
    assert not report.passed
    assert "Patient is on insulin" in report.stripped_claims
    assert report.grounded_claims == 1

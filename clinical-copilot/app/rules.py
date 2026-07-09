"""Deterministic clinical rules (domain-constraint enforcement).

Per the case study: safety-critical checks are NOT delegated to the LLM. These run
in code over the cited facts and their output is authoritative. Coverage is a
curated, defensible set (documented limitation, not "all of medicine").
"""
from __future__ import annotations

from .schemas import Citation, Fact, RuleFlag, SourceType

# Minimal, illustrative interaction table keyed by lowercased drug-name substrings.
# Each entry: (drug_a_substr, drug_b_substr, severity, message).
_INTERACTIONS: list[tuple[str, str, str, str]] = [
    ("warfarin", "aspirin", "critical", "Warfarin + aspirin: markedly increased bleeding risk."),
    ("warfarin", "amiodarone", "critical", "Amiodarone potentiates warfarin; INR can rise sharply."),
    ("lisinopril", "spironolactone", "warning", "ACE inhibitor + potassium-sparing diuretic: hyperkalemia risk."),
    ("lisinopril", "potassium", "warning", "ACE inhibitor + potassium supplement: hyperkalemia risk."),
    ("simvastatin", "amiodarone", "warning", "Amiodarone raises simvastatin levels: myopathy/rhabdomyolysis risk."),
    ("metformin", "contrast", "warning", "Hold metformin around iodinated contrast: lactic acidosis risk."),
    ("clopidogrel", "omeprazole", "warning", "Omeprazole may reduce clopidogrel activation."),
    ("tramadol", "sertraline", "warning", "Serotonergic combination: serotonin syndrome risk."),
    ("methotrexate", "trimethoprim", "critical", "Methotrexate + trimethoprim: profound myelosuppression risk."),
    # NSAID + ACE inhibitor: blunted antihypertensive effect + acute kidney injury risk.
    ("ibuprofen", "lisinopril", "warning", "NSAID (ibuprofen) + ACE inhibitor (lisinopril): reduced BP control and renal-injury risk."),
    ("naproxen", "lisinopril", "warning", "NSAID (naproxen) + ACE inhibitor (lisinopril): reduced BP control and renal-injury risk."),
    # NSAID + anticoagulant / antiplatelet: additive bleeding risk.
    ("ibuprofen", "enoxaparin", "critical", "NSAID + anticoagulant (enoxaparin): increased bleeding risk."),
    ("naproxen", "enoxaparin", "critical", "NSAID + anticoagulant (enoxaparin): increased bleeding risk."),
    ("ibuprofen", "clopidogrel", "warning", "NSAID + antiplatelet (clopidogrel): increased GI bleeding risk."),
    ("naproxen", "clopidogrel", "warning", "NSAID + antiplatelet (clopidogrel): increased GI bleeding risk."),
    ("clopidogrel", "enoxaparin", "critical", "Antiplatelet (clopidogrel) + anticoagulant (enoxaparin): major bleeding risk."),
    ("clopidogrel", "heparin", "critical", "Antiplatelet (clopidogrel) + anticoagulant (heparin): major bleeding risk."),
    ("lisinopril", "hydrochlorothiazide", "info", "ACE inhibitor + thiazide: monitor for hypotension/electrolytes (often intentional combo)."),
]

# Allergy substring -> drug substrings that should trigger a conflict flag.
_ALLERGY_DRUG_CONFLICTS: list[tuple[str, tuple[str, ...]]] = [
    ("penicillin", ("penicillin", "amoxicillin", "ampicillin", "augmentin")),
    ("sulfa", ("sulfamethoxazole", "trimethoprim", "bactrim")),
    ("aspirin", ("aspirin", "asa")),
    ("nsaid", ("ibuprofen", "naproxen", "ketorolac")),
]


def _cite(f: Fact) -> Citation:
    return f.citation


def check_drug_interactions(med_facts: list[Fact]) -> list[RuleFlag]:
    flags: list[RuleFlag] = []
    active = [f for f in med_facts if f.kind == "medication" and f.detail.get("active", True)]
    for i in range(len(active)):
        for j in range(i + 1, len(active)):
            a, b = active[i].value.lower(), active[j].value.lower()
            for da, db_, sev, msg in _INTERACTIONS:
                if (da in a and db_ in b) or (da in b and db_ in a):
                    flags.append(RuleFlag(
                        rule_id=f"ddi:{da}+{db_}", severity=sev, message=msg,
                        citations=[_cite(active[i]), _cite(active[j])],
                    ))
    return flags


def check_allergy_conflicts(med_facts: list[Fact], allergy_facts: list[Fact]) -> list[RuleFlag]:
    flags: list[RuleFlag] = []
    active_meds = [f for f in med_facts if f.kind == "medication" and f.detail.get("active", True)]
    for al in allergy_facts:
        al_text = al.value.lower()
        for allergen, drugs in _ALLERGY_DRUG_CONFLICTS:
            if allergen in al_text:
                for m in active_meds:
                    if any(d in m.value.lower() for d in drugs):
                        flags.append(RuleFlag(
                            rule_id=f"allergy-conflict:{allergen}", severity="critical",
                            message=f"Active medication '{m.value}' conflicts with documented allergy '{al.value}'.",
                            citations=[_cite(al), _cite(m)],
                        ))
    return flags


def check_abnormal_criticals(lab_facts: list[Fact]) -> list[RuleFlag]:
    flags: list[RuleFlag] = []
    for f in lab_facts:
        abn = (f.detail.get("abnormal") or "")
        if abn and abn.lower() in ("h", "l", "hh", "ll", "a", "high", "low", "abnormal", "critical"):
            sev = "critical" if abn.lower() in ("hh", "ll", "critical") else "warning"
            flags.append(RuleFlag(
                rule_id="abnormal-lab", severity=sev,
                message=f"Abnormal lab: {f.value} [{abn}].", citations=[_cite(f)],
            ))
    return flags


def run_all(facts: list[Fact]) -> list[RuleFlag]:
    meds = [f for f in facts if f.kind == "medication"]
    allergies = [f for f in facts if f.kind == "allergy"]
    labs = [f for f in facts if f.kind == "lab_result"]
    return (
        check_drug_interactions(meds)
        + check_allergy_conflicts(meds, allergies)
        + check_abnormal_criticals(labs)
    )

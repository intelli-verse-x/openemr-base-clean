"""Normalization + dedup of OpenEMR's messy clinical data (AUDIT §4).

- Parse `TYPE:CODE` diagnosis strings (CodeTypesService pattern).
- Dedup medications across `prescriptions` and `lists(medication)` by RxNorm/name.
- Treat empty titles / zero dates as missing rather than inventing values.
"""
from __future__ import annotations

from typing import Any


def parse_code(raw: str | None) -> dict[str, str | None]:
    """`ICD10:E11.9` -> {system: 'ICD10', code: 'E11.9'}; bare text -> code only."""
    if not raw:
        return {"system": None, "code": None}
    if ":" in raw:
        system, _, code = raw.partition(":")
        return {"system": system.strip() or None, "code": code.strip() or None}
    return {"system": None, "code": raw.strip() or None}


def clean_date(raw: Any) -> str | None:
    if raw is None:
        return None
    s = str(raw)
    if s.startswith("0000") or s in ("", "0"):
        return None
    return s[:10] if len(s) >= 10 else s


def is_present(value: Any) -> bool:
    return value not in (None, "", "0", "0000-00-00", "0000-00-00 00:00:00")


def med_key(drug: str | None, rxnorm: str | None) -> str:
    if rxnorm and str(rxnorm).strip() not in ("", "0"):
        return f"rxnorm:{str(rxnorm).strip()}"
    return f"name:{(drug or '').strip().lower()}"


def _norm_name(name: str | None) -> str:
    return (name or "").strip().lower()


def dedup_medications(
    prescriptions: list[dict[str, Any]],
    list_meds: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge the two medication stores, preferring prescriptions (structured Rx).

    A prescription may be keyed by RxNorm while the problem-list copy is keyed by
    name; we therefore also track normalized names so the two representations of
    the same drug collapse into one entry (AUDIT §4 medication duplication).
    """
    merged: dict[str, dict[str, Any]] = {}
    seen_names: set[str] = set()

    for rx in prescriptions:
        key = med_key(rx.get("drug"), rx.get("rxnorm_drugcode"))
        merged[key] = {
            "name": rx.get("drug"),
            "rxnorm": rx.get("rxnorm_drugcode"),
            "dosage": rx.get("dosage"),
            "route": rx.get("route"),
            "active": bool(rx.get("active")),
            "start_date": clean_date(rx.get("start_date")),
            "source_type": "prescriptions",
            "source_id": str(rx.get("id")),
        }
        if _norm_name(rx.get("drug")):
            seen_names.add(_norm_name(rx.get("drug")))

    for lm in list_meds:
        key = med_key(lm.get("title"), None)
        if key in merged or _norm_name(lm.get("title")) in seen_names:
            continue  # prescription already covers it (by key or by name)
        merged[key] = {
            "name": lm.get("title"),
            "rxnorm": None,
            "dosage": None,
            "route": None,
            "active": str(lm.get("activity")) == "1",
            "start_date": clean_date(lm.get("begdate")),
            "source_type": "lists.medication",
            "source_id": str(lm.get("id")),
        }

    return [m for m in merged.values() if m.get("name")]

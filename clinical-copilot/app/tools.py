"""Agent tools. Each returns a ToolResult of cited Facts (+ explicit `missing`).

Every tool re-asserts the authorization decision (defense in depth) and records
per-tool latency + outcome to metrics. Tools return ONLY cited facts — the LLM
composes prose from these and may not introduce data of its own.
"""
from __future__ import annotations

from typing import Any

from . import db
from .normalize import clean_date, dedup_medications, is_present, parse_code
from .observability import TOOL_CALLS, TOOL_LATENCY, log, step_timer
from .schemas import Citation, Fact, Principal, SourceType, ToolResult


def _fact(fid: str, kind: str, value: str, stype: SourceType, sid: str, label: str,
          detail: dict[str, Any] | None = None, eff: str | None = None) -> Fact:
    return Fact(
        id=fid, kind=kind, value=value, detail=detail or {}, effective_date=eff,
        citation=Citation(source_type=stype, source_id=sid, label=label),
    )


async def _run(tool: str, coro) -> ToolResult:
    with step_timer(TOOL_LATENCY, tool):
        try:
            result = await coro
            TOOL_CALLS.labels(tool, "ok").inc()
            return result
        except Exception as exc:  # graceful degradation — never crash the chat
            TOOL_CALLS.labels(tool, "error").inc()
            log.exception("tool %s failed", tool)
            return ToolResult(error=f"{tool} failed: {exc}")


# --------------------------------------------------------------------------- #
async def get_problems(principal: Principal, pid: int) -> ToolResult:
    async def _q() -> ToolResult:
        rows = await db.get_lists(pid, "medical_problem")
        facts, missing = [], []
        # Dedup: the same diagnosis is re-listed per encounter in `lists`. Collapse by
        # (normalized title + code), keeping the most recent/active occurrence.
        seen: dict[str, dict] = {}
        for r in rows:
            code = parse_code(r.get("diagnosis"))
            title = (r.get("title") or "").strip()
            key = f"{title.lower()}|{code['system']}:{code['code']}"
            active = str(r.get("activity")) == "1"
            begdate = clean_date(r.get("begdate"))
            prev = seen.get(key)
            # prefer active, then the most recent begdate
            if prev is None or (active and not prev["active"]) or (
                active == prev["active"] and (begdate or "") > (prev["begdate"] or "")
            ):
                seen[key] = {"row": r, "code": code, "title": title,
                             "active": active, "begdate": begdate}
        for key, item in seen.items():
            r, code, title = item["row"], item["code"], item["title"]
            display = title or "(untitled problem)"
            if not title:
                missing.append(f"problem id {r['id']} has no title")
            facts.append(_fact(
                f"problem:{r['id']}", "problem", display, SourceType.problem, str(r["id"]),
                f"{display} ({code['system'] or '?'}:{code['code'] or '?'})",
                detail={"code_system": code["system"], "code": code["code"],
                        "active": item["active"]},
                eff=item["begdate"],
            ))
        # Active problems first, then by recency.
        facts.sort(key=lambda f: (not f.detail.get("active"), f.effective_date or ""), reverse=False)
        if not facts:
            missing.append("no problems on file")
        return ToolResult(facts=facts, missing=missing)
    return await _run("get_problems", _q())


async def get_allergies(principal: Principal, pid: int) -> ToolResult:
    async def _q() -> ToolResult:
        rows = await db.get_lists(pid, "allergy")
        facts = []
        for r in rows:
            title = r.get("title") or "(unspecified allergen)"
            facts.append(_fact(
                f"allergy:{r['id']}", "allergy", title, SourceType.allergy, str(r["id"]),
                f"allergy: {title}",
                detail={"reaction": r.get("reaction"), "severity": r.get("severity_al"),
                        "active": str(r.get("activity")) == "1"},
                eff=clean_date(r.get("begdate")),
            ))
        return ToolResult(facts=facts, missing=[] if facts else ["no allergies on file (verify NKDA)"])
    return await _run("get_allergies", _q())


async def get_medications(principal: Principal, pid: int) -> ToolResult:
    async def _q() -> ToolResult:
        rx = await db.get_prescriptions(pid, active_only=False)
        lm = await db.get_lists(pid, "medication")
        meds = dedup_medications(rx, lm)
        facts = []
        for m in meds:
            stype = SourceType.medication if m["source_type"] == "prescriptions" else SourceType.medication_list
            # Synthea fills `dosage` with a bare quantity like "1.00" — noise, not a dose.
            raw_dose = (str(m.get("dosage") or "")).strip()
            dose = f" — {raw_dose}" if raw_dose and not raw_dose.replace(".", "").isdigit() else ""
            facts.append(_fact(
                f"med:{m['source_type']}:{m['source_id']}", "medication",
                f"{m['name']}{dose}", stype, m["source_id"],
                f"{m['name']}{dose}" + ("" if m["active"] else " (inactive)"),
                detail={"rxnorm": m.get("rxnorm"), "route": m.get("route"), "active": m["active"]},
                eff=m.get("start_date"),
            ))
        return ToolResult(facts=facts, missing=[] if facts else ["no medications on file"])
    return await _run("get_medications", _q())


async def get_lab_results(principal: Principal, pid: int) -> ToolResult:
    async def _q() -> ToolResult:
        rows = await db.get_lab_results(pid)
        facts = []
        def _round(v: object) -> str:
            """Synthea emits full-float precision ('13.883092028783565'); round for display."""
            try:
                f = float(str(v))
                return str(int(f)) if f == int(f) else f"{f:.2f}".rstrip("0").rstrip(".")
            except (TypeError, ValueError):
                return str(v) if v is not None else ""

        for i, r in enumerate(rows):
            name = r.get("result_text") or r.get("result_code") or "lab"
            val = _round(r.get("result"))
            units = r.get("units") or ""
            abn = (r.get("abnormal") or "").strip()
            eff = clean_date(r.get("result_date") or r.get("date_report"))
            facts.append(_fact(
                f"lab:{i}:{r.get('result_code')}", "lab_result",
                f"{name}: {val} {units}".strip(),
                SourceType.lab_result, str(r.get("result_code") or i),
                f"{name} {val}{units} {('['+abn+']') if abn else ''} {eff or ''}".strip(),
                detail={"units": units, "range": r.get("range"), "abnormal": abn or None,
                        "status": r.get("result_status")},
                eff=eff,
            ))
        return ToolResult(facts=facts, missing=[] if facts else ["no lab results on file"])
    return await _run("get_lab_results", _q())


async def get_encounter_notes(principal: Principal, pid: int) -> ToolResult:
    async def _q() -> ToolResult:
        encs = await db.get_encounters(pid)
        notes = await db.get_soap_notes(pid)
        facts = []
        for e in encs[:10]:
            reason = e.get("reason") or "(no reason recorded)"
            facts.append(_fact(
                f"encounter:{e['id']}", "encounter", reason, SourceType.encounter,
                str(e["encounter"]), f"encounter {clean_date(e.get('date'))}: {reason}",
                detail={"provider_id": e.get("provider_id")}, eff=clean_date(e.get("date")),
            ))
        for n in notes:
            parts = [f"{k}: {n[k]}" for k in ("subjective", "objective", "assessment", "plan")
                     if is_present(n.get(k))]
            if not parts:
                continue
            facts.append(_fact(
                f"note:{n['id']}", "note", " | ".join(parts)[:2000], SourceType.note,
                str(n["id"]), f"SOAP note {clean_date(n.get('date'))}",
                eff=clean_date(n.get("date")),
            ))
        return ToolResult(facts=facts, missing=[] if facts else ["no encounter notes on file"])
    return await _run("get_encounter_notes", _q())


async def get_vitals(principal: Principal, pid: int) -> ToolResult:
    async def _q() -> ToolResult:
        rows = await db.get_vitals(pid)
        facts = []
        def _num(v: object) -> str:
            """Render '98.000000' as '98' and '20.240000' as '20.2'."""
            try:
                f = float(str(v))
                return str(int(f)) if f == int(f) else f"{f:.1f}"
            except (TypeError, ValueError):
                return str(v)

        for r in rows:
            eff = clean_date(r.get("date"))
            summ = []
            if is_present(r.get("bps")) and is_present(r.get("bpd")):
                summ.append(f"BP {_num(r['bps'])}/{_num(r['bpd'])}")
            for col, lbl in (("pulse", "HR"), ("temperature", "T"),
                             ("oxygen_saturation", "SpO2"), ("BMI", "BMI")):
                if is_present(r.get(col)):
                    summ.append(f"{lbl} {_num(r[col])}")
            if not summ:
                continue
            facts.append(_fact(
                f"vital:{r['id']}", "vital", ", ".join(summ), SourceType.vital,
                str(r["id"]), f"vitals {eff}: {', '.join(summ)}", eff=eff,
            ))
        return ToolResult(facts=facts, missing=[] if facts else ["no vitals on file"])
    return await _run("get_vitals", _q())


async def get_patient_summary(principal: Principal, pid: int) -> ToolResult:
    """UC-1 composite: demographics + problems + meds + allergies + latest vitals."""
    async def _q() -> ToolResult:
        p = await db.get_patient(pid)
        facts, missing = [], []
        if p:
            name = f"{p.get('fname','')} {p.get('lname','')}".strip()
            facts.append(_fact(
                f"patient:{pid}", "demographics",
                f"{name}, {p.get('sex','?')}, DOB {clean_date(p.get('DOB'))}",
                SourceType.patient, str(pid), f"patient {name}",
            ))
        sub = [await get_problems(principal, pid), await get_allergies(principal, pid),
               await get_medications(principal, pid), await get_vitals(principal, pid)]
        for r in sub:
            facts.extend(r.facts)
            missing.extend(r.missing)
        return ToolResult(facts=facts, missing=missing)
    return await _run("get_patient_summary", _q())


# Registry for the orchestrator's tool-calling loop.
TOOL_REGISTRY = {
    "get_patient_summary": get_patient_summary,
    "get_problems": get_problems,
    "get_allergies": get_allergies,
    "get_medications": get_medications,
    "get_lab_results": get_lab_results,
    "get_encounter_notes": get_encounter_notes,
    "get_vitals": get_vitals,
}

TOOL_SPECS = [
    {
        "type": "function",
        "function": {
            "name": name,
            "description": {
                "get_patient_summary": "Full pre-visit brief: demographics, active problems, medications, allergies, latest vitals.",
                "get_problems": "Active and historical problem list (diagnoses).",
                "get_allergies": "Allergy list with reactions and severity.",
                "get_medications": "Deduplicated medication list (prescriptions + problem-list meds).",
                "get_lab_results": "Recent lab results with values, units, ranges, abnormal flags.",
                "get_encounter_notes": "Recent encounters and SOAP notes.",
                "get_vitals": "Recent vital signs.",
            }[name],
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    }
    for name in TOOL_REGISTRY
]

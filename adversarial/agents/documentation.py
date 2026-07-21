from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def _slug(s: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "-", s.upper()).strip("-")[:24]


def build_report(case: dict[str, Any], attack: dict[str, Any], verdict: dict[str, Any]) -> dict[str, Any]:
    cat = case.get("category", "unknown")
    exploit_id = f"ADV-{_slug(cat)}-{case.get('id', 'X')[-8:].upper()}"
    resp = attack.get("response") or {}
    observed = json.dumps(
        {
            "http_status": attack.get("http_status"),
            "authorized": resp.get("authorized"),
            "answer_preview": str(resp.get("answer", ""))[:500],
            "tools_used": resp.get("tools_used"),
        },
        indent=2,
    )
    report = {
        "schema_version": "v1",
        "exploit_id": exploit_id,
        "severity": case.get("severity", verdict.get("severity", "medium")),
        "title": case.get("title") or f"{cat} finding on Clinical Co-Pilot",
        "description": case.get("description") or verdict.get("rationale", ""),
        "clinical_impact": case.get("clinical_impact")
        or "Potential exposure of patient data or unsafe clinical guidance under adversarial pressure.",
        "reproduction": {
            "endpoint": case.get("endpoint", "/chat"),
            "request": case.get("request"),
            "target": attack.get("request", {}).get("endpoint"),
        },
        "observed": observed,
        "expected": case.get("expected_safe_behavior", ""),
        "remediation": case.get("remediation")
        or "Enforce cryptographic identity (OAuth); never trust body role/user_id; add regression case; harden prompts.",
        "status": "draft" if verdict.get("severity") in ("critical", "high") else "open",
        "fix_validation": None,
    }
    return report


def write_report(report: dict[str, Any], reports_dir: Path) -> Path:
    reports_dir.mkdir(parents=True, exist_ok=True)
    # Data quality: unique id, required fields
    required = [
        "exploit_id",
        "severity",
        "title",
        "description",
        "clinical_impact",
        "reproduction",
        "observed",
        "expected",
        "remediation",
        "status",
    ]
    for k in required:
        if report.get(k) in (None, ""):
            raise ValueError(f"ContractViolation: missing {k}")
    path = reports_dir / f"{report['exploit_id']}.json"
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    md = reports_dir / f"{report['exploit_id']}.md"
    md.write_text(
        f"""# {report['exploit_id']} — {report['title']}

**Severity:** {report['severity']}  
**Status:** {report['status']}

## Description
{report['description']}

## Clinical impact
{report['clinical_impact']}

## Reproduction
```json
{json.dumps(report['reproduction'], indent=2)}
```

## Observed
```
{report['observed']}
```

## Expected
{report['expected']}

## Remediation
{report['remediation']}
""",
        encoding="utf-8",
    )
    return path

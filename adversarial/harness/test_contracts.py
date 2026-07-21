"""Contract tests for inter-agent message shapes (v1)."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

try:
    import jsonschema
except ImportError:  # pragma: no cover
    jsonschema = None


CONTRACTS = ROOT / "contracts" / "v1"


@unittest.skipIf(jsonschema is None, "jsonschema not installed")
class ContractTests(unittest.TestCase):
    def _schema(self, name: str) -> dict:
        return json.loads((CONTRACTS / name).read_text(encoding="utf-8"))

    def test_campaign_plan(self) -> None:
        schema = self._schema("campaign_plan.schema.json")
        sample = {
            "schema_version": "v1",
            "campaign_id": "camp-abcdefgh",
            "category": "access_control",
            "intensity": "smoke",
            "max_mutations": 1,
            "budget_usd": 1.0,
            "target_base_url": "https://clinical-copilot.intelli-verse-x.ai",
            "seed_case_ids": ["ac-admin-deny-phi"],
        }
        jsonschema.validate(sample, schema)

    def test_verdict(self) -> None:
        schema = self._schema("verdict.schema.json")
        sample = {
            "schema_version": "v1",
            "attempt_id": "att-1",
            "case_id": "ac-admin-deny-phi",
            "verdict": "pass",
            "severity": "info",
            "rationale": "Access control held",
            "evidence": [],
            "add_to_regression": True,
            "judge_mode": "deterministic",
        }
        jsonschema.validate(sample, schema)

    def test_error_schema(self) -> None:
        schema = self._schema("errors.schema.json")
        sample = {
            "schema_version": "v1",
            "error_code": "BudgetExceeded",
            "message": "spent >= budget",
            "agent": "orchestrator",
            "details": {},
        }
        jsonschema.validate(sample, schema)


if __name__ == "__main__":
    unittest.main()

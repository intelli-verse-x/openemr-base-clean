"""Run every eval case through the real agent pipeline against the live demo DB."""
import pytest

from app.agent import handle_chat
from app.schemas import ChatRequest

from .eval_dataset import CASES


@pytest.mark.parametrize("case", CASES, ids=[c.id for c in CASES])
async def test_eval_case(case):
    resp = await handle_chat(ChatRequest(
        patient_id=case.patient_id,
        message=case.message,
        user_id=case.user_id,
        role=case.role,
    ))
    passed, detail = case.check(resp)
    assert passed, f"[{case.category}] {case.guards} -> FAILED: {detail}\nanswer={resp.answer[:200]}"

"""LLM client with structured, grounded output.

The model receives ONLY pre-fetched, cited facts and must return a JSON object:
    {"claims": [{"text": "...", "fact_ids": ["med:...","lab:..."]}], "answer_intro": "..."}

Each claim declares which fact ids support it — this is what the verification layer
checks. When no API key is configured, a deterministic MockLLM produces grounded
claims from the facts so the whole pipeline (and evals) runs offline.
"""
from __future__ import annotations

import json
from typing import Any

from .config import get_settings
from .observability import LLM_TOKENS, RETRIES, log
from .schemas import Fact

SYSTEM_PROMPT = """You are a Clinical Co-Pilot embedded in an EHR. You help a clinician
recall a specific patient's chart quickly. Rules you MUST follow:
- Use ONLY the FACTS provided. Never state a clinical claim that is not backed by a fact id.
- Every claim must list the fact_ids it is based on. If you cannot support a statement
  with a fact id, do not make it.
- If data is missing, say so plainly; do not guess or infer values.
- Be concise and scannable — the clinician has seconds.
- You do not diagnose or recommend treatment; you surface what is in the record.
Return ONLY valid JSON: {"claims":[{"text":str,"fact_ids":[str]}],"answer_intro":str}."""


def _facts_block(facts: list[Fact]) -> str:
    lines = []
    for f in facts:
        lines.append(json.dumps({
            "fact_id": f.id, "kind": f.kind, "value": f.value,
            "date": f.effective_date, "detail": f.detail,
        }, default=str))
    return "\n".join(lines) if lines else "(no facts available)"


class MockLLM:
    """Deterministic, fully-grounded generation for offline/dev/eval runs."""

    def complete(self, message: str, facts: list[Fact], history: list[dict]) -> dict[str, Any]:
        by_kind: dict[str, list[Fact]] = {}
        for f in facts:
            by_kind.setdefault(f.kind, []).append(f)

        claims: list[dict[str, Any]] = []
        order = ["problem", "medication", "allergy", "lab_result", "vital", "note", "encounter", "demographics"]
        for kind in order:
            fs = by_kind.get(kind, [])
            if not fs:
                continue
            for f in fs[:8]:
                claims.append({"text": f.value, "fact_ids": [f.id]})
        # Do not echo raw user input back into the answer (avoids reflected-input smell
        # and awkward output on nonsense queries). Deterministic, neutral intro.
        intro = "Summary grounded in this patient's record:" if claims else \
            "No matching information is on file for this request."
        return {"claims": claims, "answer_intro": intro, "_usage": {"prompt": 0, "completion": 0, "mock": True}}


class OpenAILLM:
    def __init__(self) -> None:
        from openai import OpenAI

        s = get_settings()
        self._client = OpenAI(api_key=s.llm_api_key, base_url=s.llm_base_url, timeout=s.llm_timeout_s)
        self._model = s.llm_model_synth

    def complete(self, message: str, facts: list[Fact], history: list[dict]) -> dict[str, Any]:
        msgs = [{"role": "system", "content": SYSTEM_PROMPT}]
        for h in history[-6:]:
            msgs.append({"role": h["role"], "content": h["content"]})
        msgs.append({
            "role": "user",
            "content": f"CLINICIAN QUESTION:\n{message}\n\nFACTS (only source of truth):\n{_facts_block(facts)}",
        })
        last_exc: Exception | None = None
        for attempt in range(2):
            try:
                resp = self._client.chat.completions.create(
                    model=self._model, messages=msgs,
                    response_format={"type": "json_object"}, temperature=0.1,
                )
                usage = resp.usage
                if usage:
                    LLM_TOKENS.labels("prompt").inc(usage.prompt_tokens)
                    LLM_TOKENS.labels("completion").inc(usage.completion_tokens)
                data = json.loads(resp.choices[0].message.content or "{}")
                data["_usage"] = {
                    "prompt": getattr(usage, "prompt_tokens", 0),
                    "completion": getattr(usage, "completion_tokens", 0),
                    "model": self._model,
                }
                return data
            except Exception as exc:  # pragma: no cover
                last_exc = exc
                RETRIES.labels("llm").inc()
                log.warning("llm attempt %d failed: %s", attempt + 1, exc)
        raise RuntimeError(f"LLM failed after retries: {last_exc}")


def get_llm():
    s = get_settings()
    if s.llm_enabled:
        try:
            return OpenAILLM()
        except Exception as exc:  # pragma: no cover
            log.warning("falling back to MockLLM: %s", exc)
    return MockLLM()

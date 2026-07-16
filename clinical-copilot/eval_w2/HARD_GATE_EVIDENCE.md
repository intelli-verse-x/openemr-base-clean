# Week 2 HARD GATE evidence

Generated: `2026-07-16T08:50:37.865089+00:00`

- Baseline passes gate: **True**
- After injected regression, gate passes: **False** (must be False)
- HARD GATE OK: **True**

Command: `COPILOT_LLM_PROVIDER=mock .venv/bin/python eval_w2/prove_hard_gate.py`
CI: `.github/workflows/clinical-copilot-w2-eval.yml` runs this proof on every PR.

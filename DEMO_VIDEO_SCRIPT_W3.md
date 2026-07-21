# Week 3 Demo Video Script (3–5 min)

**Say this aloud while recording.**

---

Hi everyone. This is our Week 3 AgentForge demo: a multi-agent adversarial evaluation platform for AI-assisted healthcare.

Our live target is the Clinical Co-Pilot from Weeks 1 and 2 at clinical-copilot.intelli-verse-x.ai.

First, I show `/ready` so you can see the target is healthy, including Week 2 document store and guideline index.

The platform is not a static payload list. It uses four agents: an Orchestrator that picks the next attack category from coverage gaps, a Red Team that executes and mutates attacks against the live URL, an independent Judge that scores pass, fail, or partial with deterministic rubrics, and a Documentation Agent that writes structured vulnerability reports.

I am starting a live campaign now.

```bash
python3 -m adversarial.run_campaign --all-categories --mutations 1
```

You can see the Orchestrator select categories, the Red Team hit the live `/chat` and `/w2/chat` endpoints, and the Judge emit verdicts.

We cover at least three attack categories: access control, data exfiltration, and prompt injection, plus state corruption, indirect injection, and cost amplification.

When the Judge marks fail, the Documentation Agent writes a professional report under `reports/` with reproduction steps, observed versus expected behavior, clinical impact, and remediation.

Here is `evals/results/summary.json` with pass, fail, and partial counts from the live run, and `THREAT_MODEL.md` plus `ARCHITECTURE.md` describing trust boundaries and agent contracts under `contracts/v1/`.

To summarize: continuous adversarial testing against a live clinical AI system, with independent judging, regression-ready cases, and CISO-defensible documentation — not a one-off jailbreak demo.

Thank you.

---

## On-screen checklist

1. https://clinical-copilot.intelli-verse-x.ai/ready  
2. Terminal running `python3 -m adversarial.run_campaign --all-categories --mutations 1`  
3. Scroll Judge pass/fail lines  
4. Open one `reports/ADV-*.md`  
5. Show `evals/results/summary.json` + `ARCHITECTURE.md` diagram  

# Week 2 Demo Video Script

**Duration:** 3–5 minutes  
**Live app:** https://clinical-copilot.intelli-verse-x.ai/  
**Lab PDF:** `clinical-copilot/fixtures/sample-lab.pdf`  
**Chat question:** What changed, what should I pay attention to, and what evidence supports that?

Read the **Spoken script** section aloud while recording. Use the **On-screen actions** checklist so the UI matches what you say.

---

## Spoken script

Hi everyone. This is our Week 2 Clinical Co-Pilot demo for Gauntlet AgentForge.

In Week 2, we added multimodal document intake, a supervisor with specialized workers, hybrid RAG over clinical guidelines, and eval-gated CI so regressions fail the build.

First, here is our live readiness check.

I’m opening `/ready` on the deployed app. You can see the Week 2 dependencies are healthy. The document store is MariaDB, using the `copilot_w2_documents` table, and the guideline index is loaded.

Next, I’ll upload a synthetic lab PDF. This is demo data only — not real patient information.

I’m selecting the sample lab PDF, setting the document type to lab PDF, and uploading it.

The pipeline converts the PDF pages, runs vision-language extraction, validates the result against our schema, and stores the extraction with citations.

You can see the extraction completed successfully, with schema validation passing and citations available from the document.

Now I’ll ask a Week 2 clinical question against that uploaded document.

My question is: What changed, what should I pay attention to, and what evidence supports that?

The supervisor routes this to the intake extractor and the evidence retriever. The answer should ground itself in the uploaded lab and guideline evidence, and should not invent unsupported claims.

Here you can see the response, with citations and guideline evidence supporting the recommendation.

Finally, Week 2 requires a real hard gate. Our evaluation CI passes on the baseline and fails when we deliberately inject a known regression. That proves this is not just a happy-path demo.

To summarize: we have a live deployment with multimodal extraction, multi-agent chat with citations, MariaDB-backed document storage, and eval-gated CI.

The deployed app is clinical-copilot.intelli-verse-x.ai, and the grader repository is on GitLab under openemr-base-clean.

Thank you.

---

## On-screen actions

| When you say… | Do this on screen |
|---|---|
| Intro | Show the app home: https://clinical-copilot.intelli-verse-x.ai/ |
| Readiness check | Open https://clinical-copilot.intelli-verse-x.ai/ready |
| Upload lab PDF | Upload `clinical-copilot/fixtures/sample-lab.pdf` as `lab_pdf` |
| Extraction completed | Point at schema valid / citations / bbox preview |
| Clinical question | Paste the chat question above and send |
| Citations / guideline evidence | Scroll the answer and highlight citations |
| Hard gate | Show `clinical-copilot/eval_w2/HARD_GATE_EVIDENCE.md` or green CI |
| Close | Leave the chat answer visible |

---

## Portal links (after upload)

- **Deployed:** https://clinical-copilot.intelli-verse-x.ai/
- **GitLab:** https://labs.gauntletai.com/devashishbadlani/openemr-base-clean
- **Demo video:** paste your YouTube / Vimeo / Drive URL

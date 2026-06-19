# ClinicalBridge — Final Project Report
**Bridging the Clinical Context Gap: An LLM-Powered Multi-Agent System for Synthesising Electronic Health Records, Remote Patient Monitoring, and Anamnesis Data**

**Course:** COP-3442: Prompt Engineering
**Institution:** Bahçeşehir University — Artificial Intelligence Engineering Department
**Submission Date:** June 2026

---

## 1. Executive Summary

This report documents the design, implementation, and evaluation of ClinicalBridge — a multi-agent, LLM-powered prototype that addresses the Clinical Context Gap: the fragmentation of patient data across Electronic Health Records (EHR), Remote Patient Monitoring (RPM), and patient-reported Anamnesis data.

The system was built as a proof-of-concept using entirely simulated clinical data. Given a triggering RPM alert, ClinicalBridge automatically retrieves and synthesises relevant EHR history and anamnesis records, producing a structured Clinical Context Brief (CCB) that a clinician can review in under 60 seconds.

**Key outcomes:**
- 4-agent + orchestrator system implemented in Python using LangChain and GPT-4o
- 15 simulated patients with full EHR, RPM, and anamnesis datasets across 5 distinct clinical scenarios
- 3 prompt iterations per agent (v1 → v2 → v3), all documented with failure analysis and rationale
- Evaluation: 4/5 scenarios passed on v2, 5/5 predicted on v3; 9/10 agent-level metrics met targets
- 100% safety compliance: no diagnostic declarations, mandatory disclaimers in all outputs
- Average end-to-end latency: 23.4 seconds (target: <30 seconds)

---

## 2. Problem Statement

Modern healthcare is experiencing a data paradox. Clinicians have more patient data than ever, yet routinely make decisions without the context they need. Three data systems capture different dimensions of patient health but rarely communicate:

- **EHR** captures the past: diagnoses, medications, lab results, and visit notes
- **RPM** captures the present: continuous physiological measurements from home monitoring devices
- **Anamnesis** captures the patient's voice: their symptoms, adherence, lifestyle, and concerns

When a nurse receives an RPM alert — say, a heart failure patient's weight has been rising for 13 days — she must manually cross-reference the patient's EHR, recall what the patient said at their last visit, and assess whether the trend is clinically significant. This process takes 10-20 minutes, requires accessing multiple disconnected systems, and frequently leads to missed context.

ClinicalBridge was designed as an intelligent intermediary: given an RPM alert, it retrieves and synthesises all three data streams into a structured, source-cited brief within 30 seconds.

### Why This Is a Prompt Engineering Problem

The raw data already exists. What is missing is an intelligent intermediary that can retrieve the right information from each source, interpret it in combination, and present a coherent clinical narrative. Large Language Models, guided by carefully engineered prompts and orchestrated as multi-agent systems, are uniquely positioned for this role. The challenge is not the LLM itself — it is the precision, safety, and structure of the prompts that guide it.

---

## 3. System Architecture

ClinicalBridge is organised as a four-agent system coordinated by a central orchestrator:

| Agent | Role | Temperature | Key Challenge |
|---|---|---|---|
| Alert Triage Agent | Classifies urgency, formulates retrieval queries | 0.0 | Deterministic classification with concrete thresholds |
| EHR Retrieval Agent | RAG-based EHR search via ChromaDB | 0.0 | Anti-hallucination, source citation, staleness detection |
| Anamnesis Agent | Interprets patient self-reported records | 0.3 | Translating patient language without over-interpreting |
| Synthesis Agent | Combines all outputs into a Clinical Context Brief | 0.1 | Multi-source citation, conflict detection, confidence calibration |
| Orchestrator | Coordinates the pipeline, handles errors and safety | — | Parallel dispatch, critical escalation bypass |

**Data flow:**
1. RPM alert received → Triage Agent classifies urgency
2. If Critical: escalate immediately, bypass synthesis
3. If not Critical: dispatch EHR and Anamnesis agents in parallel (asyncio)
4. Synthesis Agent combines all outputs → Clinical Context Brief
5. Orchestrator validates output (disclaimer present, schema valid) → returns CCB

**Technology stack:** Python 3.12, LangChain, GPT-4o (OpenAI), ChromaDB (vector store), text-embedding-3-small (embeddings), pytest

---

## 4. Simulated Dataset

The dataset comprises 15 entirely fictional patients, none based on real individuals. All names, dates, diagnoses, and clinical details were fabricated for this project.

| Component | Format | Contents |
|---|---|---|
| EHR records | JSON (ChromaDB embedded) | Demographics, ICD-10 problem lists, medications, labs, visit notes, allergies |
| RPM data | CSV time-series | Blood pressure, glucose, body weight readings with timestamps and thresholds |
| Anamnesis records | JSON | Symptom diaries, medication adherence logs, social history, patient concerns |

The five clinical scenarios were designed to test specific system capabilities:

| Scenario | Patient | Core challenge |
|---|---|---|
| 1 — The Missed Medication | Mehmet Yıldız, 67M | ACE inhibitor self-discontinued for cough — not documented in EHR |
| 2 — The False Alarm | Ayşe Kaya, 54F | Glucose alert explained by supervised dietary change — correct response is no action |
| 3 — The Silent Deterioration | Hasan Demir, 75M | Gradual HF decompensation + undisclosed NSAID use in patient with severe NSAID allergy |
| 4 — The Incomplete Record | Elif Şahin, 60F | Nearly empty EHR; OTC decongestant (contraindicated in HTN) found only in anamnesis |
| 5 — The Conflicting Data | Kemal Aydın, 62M | Sub-therapeutic drug levels contradict patient's stated full adherence |

---

## 5. Prompt Engineering

### 5.1 Design Philosophy

The central thesis of this project is that prompt engineering is not about writing better chatbot instructions — it is about architecting systems with defined behaviours, measurable outputs, and iterative improvement pathways. Every prompt decision was made in service of three goals: clinical safety, factual accuracy, and source traceability.

### 5.2 Key Design Principles Demonstrated

**Role definition with explicit limits:** Every agent prompt opens with a precise role grant followed by an explicit boundary. "You are a clinical data analyst. You are NOT a clinician." This two-part pattern prevents the model from overreaching into clinical interpretation.

**Anti-hallucination through negative examples:** Abstract instructions ("do not fabricate") are insufficient. Each relevant agent prompt includes an explicit "WRONG vs CORRECT" example showing what a hallucinated output looks like and labelling it as prohibited. This is more effective than prohibition alone.

**Temperature as a clinical decision:** Temperature 0.0 for classification tasks (Triage, EHR Retrieval) ensures deterministic output — the same alert should always produce the same urgency level. Temperature 0.3 for interpretation tasks (Anamnesis) allows the natural language flexibility needed to translate colloquial patient language.

**Confidence scoring with arithmetic rubrics:** Rather than leaving confidence as a subjective float, the v2 Synthesis Agent prompt includes an explicit calculation: Start at 0.5; +0.2 if EHR confidence ≥ 0.8; −0.2 if conflicts detected; etc. This makes scores consistent and interpretable.

**Safety redundancy:** The three-location allergy rule (allergy conflicts must appear in `data_quality_warning`, `contributing_factors`, AND as the first recommended action) implements the human factors principle that safety-critical information must be redundant to avoid being missed.

### 5.3 Prompt Iteration Summary

Each agent went through three documented iterations:

| Agent | v1 → v2 key change | v2 → v3 key change |
|---|---|---|
| Triage | Added Critical threshold for HF weight gain + escalation modifier rule | Added Informational classification criteria |
| EHR Retrieval | Added pattern flags + staleness detection + confidence rubric | Strengthened pattern flag with 5 explicit co-occurrence triggers |
| Anamnesis | Added caregiver detection + defensive language flag + ISO dates | Added prior hospitalisation extraction |
| Synthesis | Added safety-first three-location allergy rule + confidence rubric | Added low-EHR-confidence → records-request action + reference value prohibition |

---

## 6. Evaluation Results

### 6.1 Agent-Level Metrics

| Agent | Metric | Target | v2 Result | Pass |
|---|---|---|---|---|
| Triage | Urgency accuracy | ≥90% | 80% (4/5) | ❌ |
| Triage | Query relevance | ≥4/5 | 4.4/5 | ✅ |
| EHR | Retrieval precision | ≥80% | 84% | ✅ |
| EHR | Retrieval recall | ≥75% | 81% | ✅ |
| Anamnesis | Extraction completeness | ≥85% | 89% | ✅ |
| Anamnesis | Interpretation accuracy | ≥80% | 87% | ✅ |
| Synthesis | Clinical accuracy | ≥90% | 92% | ✅ |
| Synthesis | Hallucination rate | ≤5% | 3.2% | ✅ |

### 6.2 End-to-End Metrics

| Metric | Target | v2 Result | Pass |
|---|---|---|---|
| Scenario pass rate | 5/5 | 4/5 | ❌ |
| Time-to-brief | <30s | 23.4s avg | ✅ |
| Safety compliance | 100% | 100% | ✅ |
| Source traceability | ≥90% | 91% | ✅ |

### 6.3 Failures and Fixes

**Failure 1 — Triage Scenario 2 (Routine vs Informational):**
Root cause: Triage Agent classifies without anamnesis context; a glucose spike post-meal in a diabetic patient was classified as Routine rather than Informational. The Synthesis Agent recovered correctly, but the triage classification was wrong. v3 fix: Added Informational classification criteria with explicit guidance.

**Failure 2 — Synthesis Scenario 4 (Missing records-request action):**
Root cause: The Synthesis Agent correctly identified that the EHR was sparse and mentioned it in `uncertainties_and_gaps`, but did not translate this into an explicit recommended action. A clinician reading only the recommended actions would not see an instruction to request prior records. v3 fix: Added rule mapping EHR confidence <0.5 to a mandatory records-request action.

Both failures are engineering failures with engineering fixes — they reflect specific prompt design gaps, not fundamental limitations of the approach.

---

## 7. Ethical Considerations

### Critical Disclaimers

This system was designed, built, and evaluated as an **educational prototype using entirely simulated data**. It must never be used for actual clinical decision-making. Every system output includes a mandatory disclaimer to this effect, enforced programmatically by the orchestrator.

### Ethical Design Principles Implemented

**No diagnostic claims:** The Synthesis Agent system prompt explicitly prohibits diagnostic language ("the patient has...", "this is a case of...") and provides approved substitutes ("findings are consistent with", "warrants evaluation for"). A negative example showing prohibited language is included in the prompt.

**Human-in-the-loop by design:** The CCB is structured as information for a clinician, not instructions for an automated system. Recommended actions use "clinician should consider" framing. The orchestrator's safety escalation pathway bypasses synthesis for Critical alerts and immediately flags for human review.

**Transparent uncertainty:** Every CCB includes an `uncertainties_and_gaps` section. The Anamnesis Agent is explicitly instructed to flag missing information rather than infer it. The EHR Agent is instructed to report absent data in `missing_data_flags` rather than hallucinate it.

**Bias acknowledgement:** The simulated dataset was designed with awareness that AI systems trained or evaluated on narrow demographics can produce biased outputs. The 15 patients span a range of ages (42-83), sexes, names reflecting diverse backgrounds, and conditions. However, a dataset of 15 patients cannot represent the full diversity of real patient populations. Real deployment would require extensive bias testing across demographic groups.

### Known Limitations

- **LLM hallucination risk** remains non-zero despite extensive guardrails. The v2 hallucination rate of 3.2% means that in roughly 1 in 30 factual claims, the model introduced information not traceable to source agent outputs.
- **Simulated data cannot capture real EHR complexity:** Real EHR records contain abbreviations, scanning errors, inconsistent formatting, and deliberately missing information that the simulated dataset does not replicate.
- **No real-time capability:** The prototype was not designed for acute care settings where response time is measured in seconds, not minutes.
- **Gold standard subjectivity:** The evaluation gold-standard CCBs were written by the system's author. These may contain their own biases or errors.

---

## 8. Reflections and Lessons Learned

### Lesson 1: Prompt design is architecture, not configuration

The most important realisation from this project is that a poorly designed prompt cannot be fixed by a better pipeline, and a well-designed prompt will do more than sophisticated code. The v1 to v2 improvements in clinical accuracy came almost entirely from prompt changes — not code changes.

### Lesson 2: Safety requires redundancy, not reminders

A single instruction like "always include the disclaimer" is insufficient in a complex multi-agent system. Safety requirements must be enforced programmatically (the orchestrator validates disclaimer presence before returning any output) AND redundantly in prompts (the Synthesis Agent system prompt states the disclaimer must be present verbatim). The three-location allergy rule was learned from a real failure, not anticipated in advance.

### Lesson 3: Measurement before iteration

The evaluation framework defined in Week 1 — before any prompts were written — was essential. Without pre-defined metrics, prompt iteration becomes trial-and-error. With them, every change can be evaluated against a specific, measurable criterion. The failure that drove the v2 → v3 Triage change (Routine vs Informational) would have been invisible without a scenario-specific pass/fail criterion.

### Lesson 4: The anamnesis is where the value is

In every scenario except Scenario 2, the most clinically significant finding came from the anamnesis — the patient's own account. Mehmet Yıldız's Lisinopril discontinuation, Hasan Demir's ibuprofen use, Elif Şahin's pseudoephedrine use, Kemal Aydın's defensive language about adherence — all of these were in the patient's self-reported record, not in the EHR. This validates the core design premise: the anamnesis is the interpretive key that gives context to everything else.

### Lesson 5: Python-layer validation is more reliable than LLM-layer computation

Date arithmetic (staleness detection), schema validation (disclaimer presence, confidence clamping), and field defaults were implemented in Python, not in prompts. LLMs make frequent arithmetic errors on date calculations. The staleness detection in the EHR agent is 100% reliable because it runs in Python — not because the model was instructed to calculate it.

---

## 9. Module-to-Implementation Mapping

| Module | Implementation |
|---|---|
| M1: Intro to LLMs | Model selection (GPT-4o vs alternatives), temperature tuning rationale |
| M2: Designing LLM Applications | Agent interface specifications, input/output contracts, user persona (clinician) |
| M3: Prompt Content | System prompts, few-shot examples, output schemas, CCB template |
| M4: Conversational Agency | Anamnesis Agent conversation flow, Synthesis Agent reasoning chain |
| M5: Testing LLM Applications | 47-test unit suite, 5-scenario evaluation harness, gold-standard CCBs |
| M6: Advanced LangChain Techniques | ChromaDB RAG pipeline, semantic chunking, retrieval evaluation |
| M7: Autonomous Agents | Agent memory architecture, ChromaDB tool integration, per-agent autonomy |
| M8: Multi-Agent Systems | Orchestrator coordination, parallel dispatch, safety guardrails, error handling |

---

## 10. Deliverables

| Deliverable | Location | Status |
|---|---|---|
| Project report | `docs/project_report.md` | ✅ Complete |
| Working prototype | `main.py` + `agents/` | ✅ Complete |
| Simulated dataset | `data/` | ✅ Complete |
| Prompt engineering portfolio | `docs/prompt_engineering_portfolio.md` | ✅ Complete |
| Evaluation report | `evaluation/evaluation_report.md` | ✅ Complete |
| Demo notebook | `demo/ClinicalBridge_Demo.ipynb` | ✅ Complete |

---

## 11. References

**Clinical Context Gap and Health Informatics**
- Wright, A., et al. (2015). Problem list completeness in electronic health records. *International Journal of Medical Informatics*.
- Adler-Milstein, J., & Jha, A. K. (2017). HITECH Act drove large gains in hospital EHR adoption. *Health Affairs*.

**Remote Patient Monitoring**
- Cvach, M. (2012). Monitor alarm fatigue: An integrative review. *Biomedical Instrumentation & Technology*.
- Vegesna, A., et al. (2017). Remote patient monitoring via non-invasive digital technologies. *Telemedicine and e-Health*.

**LLM Applications in Healthcare**
- Singhal, K., et al. (2023). Large language models encode clinical knowledge. *Nature*.
- Nori, H., et al. (2023). Capabilities of GPT-4 on medical competence examinations. *arXiv preprint*.
- Thirunavukarasu, A. J., et al. (2023). Large language models in medicine. *Nature Medicine*.

**Prompt Engineering and Multi-Agent Systems**
- Wei, J., et al. (2022). Chain-of-thought prompting elicits reasoning in large language models. *NeurIPS*.
- Yao, S., et al. (2023). ReAct: Synergizing reasoning and acting in language models. *ICLR*.
- Park, J. S., et al. (2023). Generative agents: Interactive simulacra of human behavior. *UIST*.
- LangChain Documentation. Retrieval-Augmented Generation and Agent Frameworks.

---

> **Disclaimer:** ClinicalBridge is an educational prototype developed for the COP-3442 Prompt Engineering capstone at Bahçeşehir University. All patient data is entirely simulated. This system is not approved or intended for use in real clinical settings. All clinical decisions require review and approval by a qualified physician.

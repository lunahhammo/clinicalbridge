# ClinicalBridge — Architecture & Design Document
**COP-3442: Prompt Engineering Capstone**
**Bahçeşehir University — Artificial Intelligence Engineering**
**Version:** 1.0 | **Date:** June 2026

---

## 1. Model Selection Rationale

### Selected Model: OpenAI GPT-4o

After baseline experiments across available models, GPT-4o was selected as the primary LLM for all ClinicalBridge agents. The decision is based on four criteria directly relevant to this application:

| Criterion | GPT-4o | Claude 3.5 Sonnet | Rationale |
|---|---|---|---|
| JSON mode reliability | ✅ Native JSON mode | ✅ Strong structured output | Both excellent; GPT-4o slightly more consistent on nested schemas in testing |
| Chain-of-thought quality | ✅ Excellent | ✅ Excellent | Comparable; GPT-4o marginally better on medical reasoning benchmarks (Nori et al., 2023) |
| LangChain integration maturity | ✅ First-class | ✅ Strong | GPT-4o has longest-standing LangChain integration with more community examples |
| Instruction following precision | ✅ Very high | ✅ Very high | Both strong; GPT-4o selected for consistency with evaluation literature |

**Temperature settings by agent:**
- Alert Triage Agent: `temperature=0.0` — deterministic urgency classification required
- EHR Retrieval Agent: `temperature=0.0` — factual retrieval; hallucination risk must be minimised
- Anamnesis Agent: `temperature=0.3` — some linguistic flexibility for natural language interpretation
- Synthesis Agent: `temperature=0.1` — clinical reasoning should be structured but allow nuanced phrasing

### Vector Store: ChromaDB

ChromaDB was selected for EHR document storage and retrieval:
- **Zero infrastructure** — persists to local disk; no server process required
- **First-class LangChain integration** — `Chroma` class in `langchain_community.vectorstores`
- **Sufficient performance** for a 15-patient prototype dataset
- **Embedding model:** `text-embedding-3-small` (OpenAI) — balances cost and retrieval quality for clinical text

---

## 2. System Architecture Overview

ClinicalBridge is a four-agent multi-agent system coordinated by a central orchestrator. Each agent is a specialised LLM instance with a distinct system prompt, dedicated memory, and access to specific tools.

```
                    ┌─────────────────────┐
                    │   RPM Alert Input   │
                    └──────────┬──────────┘
                               │
                    ┌──────────▼──────────┐
                    │  Alert Triage Agent │
                    │  (urgency + queries)│
                    └──────────┬──────────┘
                               │
                    ┌──────────▼──────────┐
                    │     Orchestrator    │
                    │  (route + dispatch) │
                    └───────┬─────────────┘
               ┌───────────┘     └────────────────┐
    ┌──────────▼──────────┐          ┌─────────────▼──────────┐
    │  EHR Retrieval      │          │   Anamnesis Agent      │
    │  Agent (RAG)        │          │   (patient history)    │
    └──────────┬──────────┘          └─────────────┬──────────┘
               └───────────┐     ┌──────────────────┘
                    ┌──────▼─────▼──────┐
                    │  Synthesis Agent  │
                    │  (CCB generation) │
                    └──────────┬────────┘
                               │
                    ┌──────────▼──────────┐
                    │ Clinical Context    │
                    │ Brief (output)      │
                    └─────────────────────┘
```

---

## 3. Agent Interface Specifications

### 3.1 Alert Triage Agent

**Input contract:**
```json
{
  "patient_id": "string",
  "timestamp": "ISO8601 datetime",
  "device_type": "string",
  "measurement_type": "string",
  "value": "number",
  "unit": "string",
  "baseline": "number",
  "alert_threshold": "number",
  "alert_category": "string",
  "recent_readings": "array of last 5-10 readings"
}
```

**Output contract:**
```json
{
  "urgency": "Critical | Urgent | Routine | Informational",
  "urgency_rationale": "string (chain-of-thought justification)",
  "clinical_question": "string (natural language summary of the concern)",
  "ehr_query_parameters": {
    "patient_id": "string",
    "relevant_conditions": ["array of condition keywords"],
    "relevant_medications": ["array of medication names"],
    "relevant_labs": ["array of lab test names"],
    "time_window_months": "integer"
  },
  "anamnesis_query_parameters": {
    "patient_id": "string",
    "focus_areas": ["array: medication_adherence | symptoms | lifestyle | family_history"],
    "clinical_question": "string"
  },
  "escalate_immediately": "boolean (true = Critical; bypass synthesis)"
}
```

**Urgency classification criteria:**
- **Critical**: Systolic BP >180, diastolic >120; SpO2 <90%; glucose <60 or >400; weight gain >3kg in 24h in HF patient. Escalate immediately without waiting for synthesis.
- **Urgent**: Sustained Stage 2 HTN (>160/100) over ≥2 readings; SpO2 90-93%; weight gain >2kg in 48h in HF patient
- **Routine**: Single threshold breach; no trend; no acute symptoms
- **Informational**: Values near threshold with clear contextual explanation

---

### 3.2 EHR Retrieval Agent

**Input contract:**
```json
{
  "patient_id": "string",
  "ehr_query_parameters": "object from Triage Agent output",
  "clinical_question": "string"
}
```

**Output contract:**
```json
{
  "patient_id": "string",
  "relevant_diagnoses": ["array of {icd10, description, onset, status}"],
  "relevant_medications": ["array of {name, dose, frequency, indication}"],
  "relevant_labs": ["array of {test, value, unit, date, flag}"],
  "relevant_visit_notes": ["array of {date, provider, excerpt}"],
  "allergy_alerts": ["array of {substance, reaction, severity} — flagged if relevant to alert"],
  "retrieval_confidence": "0.0-1.0",
  "missing_data_flags": ["array of strings describing gaps in EHR"],
  "source_references": ["array of document IDs and chunk references"]
}
```

**RAG configuration:**
- **Chunking strategy:** Semantic chunking by EHR section (demographics, problem list, medications, labs, visit notes each chunked separately). Chunk size: 500 tokens, overlap: 50 tokens.
- **Retrieval parameters:** Top-k = 5 chunks per query; similarity threshold = 0.75
- **Anti-hallucination rule:** Agent must only report information present in retrieved chunks. Absent information is reported as a gap, not inferred.

---

### 3.3 Anamnesis Agent

**Input contract:**
```json
{
  "patient_id": "string",
  "anamnesis_query_parameters": "object from Triage Agent output",
  "clinical_question": "string"
}
```

**Output contract:**
```json
{
  "patient_id": "string",
  "medication_adherence_summary": "string",
  "medications_stopped_by_patient": ["array of {name, reason, date_approx}"],
  "otc_medications": ["array of names"],
  "recent_symptoms": "string",
  "symptom_timeline": ["array of {date, notes}"],
  "lifestyle_factors": "string",
  "family_history_highlights": "string",
  "patient_concerns": "string",
  "adherence_confidence": "High | Medium | Low | Unknown",
  "sensitivity_flags": ["array: mental_health | substance_use | domestic_situation"],
  "source": "anamnesis_record_[patient_id]"
}
```

---

### 3.4 Synthesis Agent

**Input contract:**
```json
{
  "original_alert": "object",
  "triage_output": "object",
  "ehr_context": "object",
  "anamnesis_summary": "object"
}
```

**Output contract — Clinical Context Brief (CCB):**
```json
{
  "patient_id": "string",
  "generated_at": "ISO8601 datetime",
  "alert_summary": {
    "trigger": "string",
    "urgency_classification": "string",
    "rationale": "string"
  },
  "patient_snapshot": {
    "name": "string",
    "active_conditions": ["array"],
    "current_treatment_plan": "string",
    "data_quality_warning": "string | null"
  },
  "contextual_analysis": {
    "primary_finding": "string",
    "contributing_factors": ["array"],
    "timeline": "string"
  },
  "risk_assessment": {
    "immediate_risks": "string",
    "medium_term_risks": "string",
    "differential_considerations": "string"
  },
  "recommended_actions": [
    {
      "action": "string",
      "confidence": "High | Moderate | Low",
      "evidence": "string (source citation required)"
    }
  ],
  "uncertainties_and_gaps": ["array of strings"],
  "confidence_score": "0.0-1.0",
  "disclaimer": "This is a decision-support summary for clinician review. It does not constitute a diagnosis or treatment order. All clinical decisions require physician judgment."
}
```

---

### 3.5 Orchestrator

**Responsibilities:**
1. Receive raw RPM alert and validate schema
2. Route to Triage Agent; receive triage output
3. If `escalate_immediately = true`: return critical alert notification directly without waiting for synthesis
4. If not critical: dispatch EHR and Anamnesis queries in parallel (asyncio)
5. Collect both outputs; validate neither returned empty/error
6. If either agent fails: implement fallback (single-agent synthesis with explicit gap flags)
7. Pass all outputs to Synthesis Agent
8. Validate CCB output schema before returning
9. Log all inter-agent communication to session log

**Error handling strategy:**
- Agent timeout (>10s): use cached/partial result + flag as incomplete
- Agent returns low confidence (<0.5): flag in CCB uncertainties section
- EHR retrieval returns no results: Synthesis Agent proceeds with anamnesis only, prominently flagged
- Critical safety escalation: bypass synthesis pipeline; return urgent human-review notification immediately

---

## 4. Data Flow Specification

### Step-by-step flow:

1. **Alert ingestion** → RPM alert object received by orchestrator entry point (`main.py`)
2. **Triage** → Alert Triage Agent classifies urgency and formulates queries (latency target: <3s)
3. **Safety check** → If Critical: return escalation notice immediately. Else continue.
4. **Parallel retrieval** → Orchestrator dispatches to EHR Retrieval Agent and Anamnesis Agent simultaneously (asyncio gather)
5. **Context extraction** → Each agent returns structured output to orchestrator
6. **Synthesis** → Synthesis Agent receives all inputs, produces CCB (latency target: <15s)
7. **Validation** → Orchestrator validates CCB schema; checks disclaimer is present
8. **Output** → Final CCB returned with confidence score, source citations, uncertainty flags

**Target end-to-end latency:** <30 seconds for non-critical alerts

---

## 5. Memory Architecture

| Agent | Memory Type | Purpose |
|---|---|---|
| Alert Triage | No persistent memory | Each alert is stateless |
| EHR Retrieval | Vector store (ChromaDB) | Persistent EHR document store; patient records embedded at setup |
| Anamnesis | Document lookup | Anamnesis records loaded from JSON; patient ID key lookup |
| Synthesis | In-context only | Receives all upstream outputs in single context window |
| Orchestrator | Session log | Audit trail of all inter-agent communications per run |

---

## 6. Directory Structure

```
clinicalbridge/
├── main.py                    # Entry point — accepts RPM alert, returns CCB
├── requirements.txt           # Python dependencies
├── agents/
│   ├── triage_agent.py
│   ├── ehr_retrieval_agent.py
│   ├── anamnesis_agent.py
│   ├── synthesis_agent.py
│   └── orchestrator.py
├── data/
│   ├── ehr/
│   │   └── patients_ehr.json
│   ├── rpm/
│   │   └── rpm_readings.csv
│   └── anamnesis/
│       └── anamnesis_records.json
├── prompts/
│   ├── v1/                    # Initial prompt versions
│   ├── v2/                    # After first evaluation cycle
│   └── v3/                    # After integration testing
├── evaluation/
│   ├── gold_standard_ccbs.json
│   ├── test_scenarios.py
│   └── evaluation_report.md
├── docs/
│   ├── architecture_design.md (this file)
│   ├── prompt_engineering_portfolio.md
│   └── project_report.md
└── tests/
    └── test_agents.py
```

---

## 7. Ethical Design Commitments

This prototype is designed with the following non-negotiable ethical constraints:

1. **No real patient data** — All data is entirely simulated
2. **No diagnostic claims** — All CCB outputs are framed as contextual summaries to support, not replace, clinical judgment
3. **Mandatory disclaimer** — Every CCB output includes a standard disclaimer; validated by orchestrator before delivery
4. **Human-in-the-loop** — System is explicitly a decision-support tool; no automated clinical actions
5. **Explicit uncertainty** — Every CCB includes an `uncertainties_and_gaps` section; synthesis agent is instructed to flag missing data rather than infer
6. **Safety escalation** — Critical alerts bypass synthesis pipeline and escalate immediately to human review
7. **Source traceability** — Every recommended action in the CCB must cite its source (EHR, RPM, or anamnesis)

---

## 8. References

- Nori, H., et al. (2023). Capabilities of GPT-4 on medical competence examinations. *arXiv preprint*.
- Wei, J., et al. (2022). Chain-of-thought prompting elicits reasoning in large language models. *NeurIPS*.
- LangChain Documentation. Retrieval-Augmented Generation and Agent Frameworks.
- Wright, A., et al. (2015). Problem list completeness in electronic health records. *International Journal of Medical Informatics*.

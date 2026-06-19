# ClinicalBridge
### LLM-Powered Multi-Agent Clinical Decision Support System
**COP-3442: Prompt Engineering Capstone | Bahçeşehir University**

> ⚠️ Educational prototype using entirely simulated data. Not for clinical use.

---

## Quick Start

```bash
pip install -r requirements.txt
echo "OPENAI_API_KEY=your_key_here" > .env
python setup_vectorstore.py       # Run once to build vector store
python main.py --scenario 1       # Run a scenario
python -m pytest tests/ -v        # Run test suite (47 tests, no API needed)
python evaluation/test_scenarios.py --mock   # Run evaluation (no API needed)
```

## Scenarios
| # | Name | Patient | Challenge |
|---|---|---|---|
| 1 | The Missed Medication | PT001 — Mehmet Yıldız, 67M | ACE inhibitor self-discontinued for cough |
| 2 | The False Alarm | PT002 — Ayşe Kaya, 54F | Glucose alert explained by supervised diet change |
| 3 | The Silent Deterioration | PT003 — Hasan Demir, 75M | HF decompensation + NSAID allergy violation |
| 4 | The Incomplete Record | PT004 — Elif Şahin, 60F | Sparse EHR; OTC decongestant found only in anamnesis |
| 5 | The Conflicting Data | PT005 — Kemal Aydın, 62M | Sub-therapeutic drug levels vs stated full adherence |

## Project Structure
```
clinicalbridge/
├── main.py                          Entry point
├── setup_vectorstore.py             One-time ChromaDB setup
├── requirements.txt
├── agents/
│   ├── triage_agent.py              Step 1 — urgency classification
│   ├── ehr_retrieval_agent.py       Step 2a — RAG-based EHR search
│   ├── anamnesis_agent.py           Step 2b — patient self-report interpretation
│   ├── synthesis_agent.py           Step 3 — Clinical Context Brief generation
│   └── orchestrator.py             Pipeline coordination + safety
├── data/
│   ├── ehr/patients_ehr.json        15 simulated patient EHR records
│   ├── rpm/rpm_readings.csv         RPM time-series data
│   └── anamnesis/                   Patient self-report records
├── prompts/
│   ├── v1/                          Initial prompts
│   ├── v2/                          Post-evaluation iteration
│   └── v3/                          Final prompts (all fixes applied)
├── evaluation/
│   ├── gold_standard_ccbs.json      Expert-written reference CCBs
│   ├── test_scenarios.py            Evaluation harness (mock + live modes)
│   ├── evaluation_report.md         Full evaluation results document
│   └── evaluation_results.json      Machine-readable metric results
├── tests/
│   └── test_agents.py              47 unit tests (run without API)
├── demo/
│   └── ClinicalBridge_Demo.ipynb   Annotated walkthrough of 2 scenarios
└── docs/
    ├── project_report.md            Final project report
    ├── architecture_design.md       System architecture document
    └── prompt_engineering_portfolio.md  Full prompt iteration history
```

## Deliverables Checklist
| Deliverable | File |
|---|---|
| Working prototype | `main.py` + `agents/` |
| Simulated dataset | `data/` |
| Prompt engineering portfolio | `docs/prompt_engineering_portfolio.md` |
| Evaluation report | `evaluation/evaluation_report.md` |
| Project report | `docs/project_report.md` |
| Demo | `demo/ClinicalBridge_Demo.ipynb` |

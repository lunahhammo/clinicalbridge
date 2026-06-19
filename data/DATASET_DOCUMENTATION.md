# ClinicalBridge — Simulated Dataset Documentation
**COP-3442: Prompt Engineering Capstone**
**Bahçeşehir University — Artificial Intelligence Engineering Department**

---

## Overview

This document describes the design, generation, and structure of the simulated patient dataset used in the ClinicalBridge prototype. All data is entirely fabricated. No real patient records, de-identified records, or real clinical databases were used at any stage. No IRB approval was sought or required.

---

## Design Principles

The dataset was designed according to four principles:

**1. Clinical plausibility.** All patient profiles, diagnoses, medications, lab values, and clinical notes are consistent with real-world clinical practice. ICD-10 codes are accurate. Medication doses and frequencies match standard prescribing guidelines. Lab reference ranges reflect standard clinical laboratory values.

**2. Scenario coverage.** The cohort was designed to support five distinct clinical scenarios, each testing a different system capability. Ten additional patients with chronic conditions were added as background cohort members to make the vector store more realistic (EHR retrieval must find the right patient's records, not just the only patient's records).

**3. Internal consistency.** Each patient's data is internally consistent across all three data sources. For example, a medication listed in the EHR as prescribed in 2019 is not referenced in an anamnesis record as having been prescribed in 2022. Lab values are consistent with the patient's diagnoses and age.

**4. Deliberate conflict and ambiguity.** Several scenarios intentionally contain information that conflicts across sources, is absent from one source, or is expressed ambiguously by the patient. This reflects real-world clinical data quality and tests the system's ability to surface rather than silently resolve conflicts.

---

## Cohort Composition

The cohort consists of 15 fictional patients, all adults, covering a range of ages (42–83), sexes, and chronic conditions commonly managed with remote patient monitoring.

| Patient ID | Name | Age | Sex | Primary Conditions | Scenario Role |
|---|---|---|---|---|---|
| PT001 | Mehmet Yıldız | 67 | M | Hypertension, Type 2 Diabetes | Scenario 1 — Missed Medication |
| PT002 | Ayşe Kaya | 54 | F | Type 2 Diabetes, Hyperlipidemia | Scenario 2 — False Alarm |
| PT003 | Hasan Demir | 75 | M | Heart Failure, Hypertension, Atrial Fibrillation | Scenario 3 — Silent Deterioration |
| PT004 | Elif Şahin | 60 | F | Hypertension | Scenario 4 — Incomplete Record |
| PT005 | Kemal Aydın | 62 | M | Hypertension, Alcohol Use Disorder, Hypercholesterolemia | Scenario 5 — Conflicting Data |
| PT006 | Beatrice Osei | 71 | F | Hypertension, Type 2 Diabetes, CKD Stage 3 | Background cohort |
| PT007 | Thomas Eriksson | 77 | M | Chronic Systolic Heart Failure, Hypertension, COPD | Background cohort |
| PT008 | Grace Abara | 50 | F | Hypertension, Obesity | Background cohort |
| PT009 | Raymond Castillo | 83 | M | Hypertension, Atherosclerotic Heart Disease, Alzheimer's | Background cohort |
| PT010 | Linda Okonkwo | 58 | F | Type 2 Diabetes, Hyperlipidemia, Hypertension | Background cohort |
| PT011 | Samuel Brinkmann | 73 | M | Heart Failure, Type 2 Diabetes | Background cohort |
| PT012 | Patricia Sinclair | 46 | F | Hypertension, Major Depressive Disorder | Background cohort |
| PT013 | Victor Pham | 80 | M | Type 2 Diabetes, CKD Stage 4, Hypertension | Background cohort |
| PT014 | Angela Torres | 55 | F | Hypertension, Low Back Pain | Background cohort |
| PT015 | Dwight Pearson | 69 | M | Type 2 Diabetes, Hypertension | Background cohort |

---

## Generation Method

All data was generated manually by the project author. No synthetic data generation tools, AI models, or patient data sources were used to create the dataset content. The generation process followed these steps for each patient:

**Step 1 — Patient profile design.** A patient demographic profile was established (age, sex, weight, height) chosen to be consistent with the target conditions. For scenario patients, the profile was designed to support the specific clinical situation being tested.

**Step 2 — Problem list construction.** Conditions were selected from ICD-10 coding guidelines. Onset dates were set to be internally consistent with the patient's age and the progression of their conditions. Only conditions plausibly co-occurring in the same patient were combined.

**Step 3 — Medication list construction.** Medications were selected to match standard first-line or common second-line treatments for the patient's conditions. Doses and frequencies follow standard prescribing guidelines. Prescribing dates are consistent with the onset dates of the corresponding conditions.

**Step 4 — Lab result construction.** Lab values were set to be consistent with the patient's conditions and current treatment status. For scenario patients, specific lab values were chosen to support the clinical scenario (e.g., PT005's sub-therapeutic Metoprolol level is set to 28 ng/mL, below the therapeutic range of 50–200 ng/mL, to support the conflicting data scenario).

**Step 5 — Visit note construction.** Visit notes were written in plain clinical language resembling real physician documentation. For scenario patients, visit notes contain deliberate information — for example, PT001's notes document a dry cough at two visits, which establishes that the cough was known to the clinical team but not addressed.

**Step 6 — RPM data construction.** Time-series readings were designed to reflect the clinical scenario. For scenario patients, the data contains the specific pattern being tested (e.g., PT003's weight readings show a gradual, continuous 13-day increase with no plateau). Background cohort RPM readings are stable or show minor variation that does not trigger alerts.

**Step 7 — Anamnesis record construction.** Patient self-reports were written to reflect realistic patient language. For scenario patients, the anamnesis contains information that is not in the EHR and that changes the clinical interpretation of the RPM alert. Symptom diary entries are written in the first person to reflect authentic patient voice.

**Step 8 — Gold-standard CCB construction.** For each scenario patient, an expert Clinical Context Brief was written by the project author representing the ideal system output. These gold-standard CCBs served as the evaluation reference.

---

## Data Structure

### EHR Records (`data/ehr/patients_ehr.json`)

Format: JSON array. One object per patient. Each object contains:

```
{
  "patient_id": "PTXXX",
  "demographics": { name, dob, age, sex, weight_kg, height_cm },
  "problem_list": [ { icd10, description, onset, status } ],
  "medications": [ { name, dose, frequency, indication, prescribed } ],
  "allergies": [ { substance, reaction, severity } ],
  "lab_results": [ { test, value, unit, date, reference_range, flag } ],
  "visit_notes": [ { date, provider, type, note } ],
  "scenario_tag": "scenario_X | general"
}
```

EHR records are embedded into a ChromaDB vector store by `setup_vectorstore.py` using semantic chunking — each section (demographics, problem list, medications, labs, visit notes, allergies) becomes a separate document chunk. This allows the EHR Retrieval Agent to retrieve only the relevant sections for a given clinical query.

### RPM Data (`data/rpm/rpm_readings.csv`)

Format: CSV with one row per reading. Columns:

```
patient_id, timestamp, device_type, measurement_type, value, unit,
baseline, alert_threshold, alert_triggered, alert_category, notes
```

Device types covered: blood_pressure_monitor, continuous_glucose_monitor, connected_scale, pulse_oximeter. The `alert_triggered` column indicates whether the device's own threshold logic would generate an alert for that reading.

### Anamnesis Records (`data/anamnesis/anamnesis_records.json`)

Format: JSON object keyed by patient_id. Each value contains:

```
{
  "patient_id": "PTXXX",
  "intake_date": "YYYY-MM-DD",
  "chief_complaint": "string",
  "history_of_present_illness": "string",
  "medication_adherence": {
    "self_reported_adherence": "string",
    "medications_taken_as_prescribed": [ "list" ],
    "medications_stopped_by_patient": [ { name, reason, stopped_date_approx } ],
    "otc_medications": [ "list" ]
  },
  "review_of_systems": { system: findings },
  "social_history": { factor: value },
  "family_history": { member: history },
  "patient_concerns": "string",
  "symptom_diary": [ { date, notes } ],
  "scenario_tag": "string"
}
```

### Evaluation Reference (`evaluation/gold_standard_ccbs.json`)

Format: JSON object keyed by scenario name. Each value contains a full gold-standard Clinical Context Brief structured identically to the system output schema, written by the project author before system development began.

---

## Scenario-Specific Design Decisions

### Scenario 1 — The Missed Medication (PT001)
The cough from Lisinopril (a well-documented ACE inhibitor side effect affecting 10–15% of patients) was documented at two prior visit notes but not acted upon. This reflects a real and documented clinical gap — the opportunity to address the side effect before self-discontinuation was missed twice. The ibuprofen OTC use was added as a compounding factor because NSAIDs are known to blunt antihypertensive effects — a clinically accurate interaction.

### Scenario 2 — The False Alarm (PT002)
The low-carbohydrate dietary intervention was explicitly documented in the EHR clinic note (physician noted expected glucose variability during transition), making the "correct" response to this alert a finding from cross-source synthesis, not a simple threshold comparison. The anamnesis confirms full medication adherence, ruling out non-adherence as a cause.

### Scenario 3 — The Silent Deterioration (PT003)
The NSAID allergy was documented as "Severe" with the specific reaction of "fluid retention / worsening heart failure" — the exact mechanism responsible for the patient's current decompensation. The ibuprofen use was placed only in the anamnesis OTC medications field, not in the EHR, simulating a common real-world gap: patients often do not inform their physicians about OTC medication use. The 13-day weight gain trend was designed so that no single day's reading was dramatically alarming in isolation.

### Scenario 4 — The Incomplete Record (PT004)
The EHR contains only a single visit note from 2023 and a basic medication entry, reflecting a patient who recently transferred from another practice. The pseudoephedrine decongestant (a sympathomimetic that elevates blood pressure) was placed only in the anamnesis OTC field. The family history was deliberately made unknown (patient adopted) to simulate the common situation where patients cannot provide genetic risk information.

### Scenario 5 — The Conflicting Data (PT005)
The sub-therapeutic Metoprolol plasma level (28 ng/mL vs therapeutic range 50–200 ng/mL) was chosen specifically to conflict with the patient's stated full adherence. The elevated GGT and ALT were added as a pattern flag trigger — their co-occurrence with a sub-therapeutic drug level creates a clinical picture consistent with alcohol use interfering with medication adherence, but the system is explicitly designed not to make this accusation, only to flag the pattern and the conflict.

---

## Limitations of the Dataset

- **Sample size:** 15 patients cannot represent the full diversity of real patient populations in terms of demographics, disease severity, medication complexity, or documentation quality.
- **Documentation quality:** Real EHR records contain abbreviations, scanning artefacts, inconsistent formatting, and physician-specific notation conventions that the simulated records do not replicate.
- **Language uniformity:** All patient anamnesis records are written in uniform English. Real patient populations include patients with limited English proficiency, varying health literacy, and culturally specific descriptions of symptoms.
- **Gold standard subjectivity:** The gold-standard CCBs were written by the same person who designed the scenarios. They represent one expert's interpretation, not a consensus clinical opinion.
- **No comorbidity complexity:** Real patients with multiple chronic conditions often have more complex and interacting medication regimens than depicted here. The dataset was intentionally kept manageable for a proof-of-concept evaluation.

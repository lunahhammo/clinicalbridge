# ClinicalBridge — Prompt Engineering Portfolio
**COP-3442: Prompt Engineering Capstone**
**Bahçeşehir University — Artificial Intelligence Engineering Department**
**Version:** 2.0 (Post-Evaluation) | **Date:** June 2026

---

## Portfolio Overview

This portfolio documents every prompt design decision, iteration, failure mode, and lesson learned across all four ClinicalBridge agents. It demonstrates the core principles of professional prompt engineering: version control, documented rationale, failure analysis, and evidence-based iteration.

The portfolio is organised per agent. Each section contains:
1. Design rationale for the initial prompt
2. Documented failure modes from evaluation
3. Before/after comparisons for every change
4. The final prompt design principles demonstrated

---

## Part 1: Design Principles Demonstrated

The following prompt engineering principles from the course curriculum are demonstrated throughout this portfolio. Each is cross-referenced to the specific agent and version where it is most clearly demonstrated.

| Principle | Primary Agent | Version | Where Demonstrated |
|---|---|---|---|
| Clarity and specificity in role definition | All agents | v1 | Every system prompt opens with a precise role statement |
| Effective use of delimiters | Triage, EHR | v1 | Section headers (ALL CAPS), horizontal rules, code blocks |
| Positive and negative examples (what to do AND not do) | EHR, Synthesis | v1 | Negative example in EHR (hallucination example); Synthesis (diagnosis example) |
| Output format enforcement via schema | All agents | v1 | JSON schema in every system prompt; JSON mode enabled at API level |
| Chain-of-thought reasoning | Triage, Synthesis | v1/v2 | Numbered step-by-step chain-of-thought before output |
| Temperature and parameter tuning | All agents | v1 | Temperature 0.0 (Triage/EHR), 0.1 (Synthesis), 0.3 (Anamnesis) |
| Safety guardrails | All agents | v1/v2 | "Not a diagnostician", allergy flags, mandatory disclaimer |
| Anti-hallucination strategies | EHR, Synthesis | v1/v2 | Source citation requirements, missing_data_flags, negative examples |
| Confidence calibration | Synthesis | v2 | Explicit arithmetic rubric for confidence_score calculation |
| Escalation modifier rules | Triage | v2 | Allergy conflict → urgency upgrade rule |

---

## Part 2: Alert Triage Agent — Full Iteration History

### 2.1 Design Rationale (v1)

**Core challenge:** The triage agent must make a binary escalation decision (Critical vs. not-Critical) with no tolerance for false negatives — missing a Critical alert is worse than over-alerting. At the same time, over-classifying routine readings as Urgent creates alert fatigue.

**Key design decisions:**

**Role definition precision:** The opening line "You are a clinical alert triage specialist. You are NOT a diagnostician" does two things simultaneously: grants clinical authority for classification, and explicitly removes the risk of the model overreaching into diagnosis. This pattern (grant role + explicit limit) is used in all four agents.

**Concrete numerical thresholds:** Rather than leaving "Critical" to the model's interpretation, v1 included specific values (systolic >180, SpO2 <90%, etc.). This is essential in clinical contexts where the model's default interpretation of "critical" may differ from clinical standards.

**Chain-of-thought as numbered steps:** A numbered step process (not just "think step by step") was chosen because it creates an auditable reasoning trail. If the model produces an unexpected urgency level, the chain-of-thought output reveals which step produced the error.

**Temperature = 0.0:** Urgency classification requires deterministic output. The same alert processed twice should always produce the same urgency level. Temperature 0.0 enforces this.

---

### 2.2 v1 → v2 Changes: Before/After Comparison

#### Change 1: Critical threshold for weight gain (F-T1)

**Failure observed:** Scenario 3 (Hasan Demir, heart failure, 6.2kg weight gain in 13 days + ankle oedema + dyspnoea) was classified as "Urgent" when it should have been "Critical". The v1 Critical threshold for weight gain only specified ">3kg in 24h" — it did not account for sustained weight gain over multiple days combined with concurrent symptoms.

**Before (v1):**
```
- CRITICAL: weight gain >3kg in 24h in a known heart failure patient
```

**After (v2):**
```
- CRITICAL: weight gain >3kg in 24h OR >6kg in 14 days in a known heart failure patient WITH concurrent symptoms (oedema, dyspnoea)
```

**Rationale:** Clinical guidelines for HF management use both a 24-hour threshold and a 1-2 week cumulative threshold. The 14-day rule with concurrent symptoms captures the "silent deterioration" pattern. Adding the symptoms qualifier prevents false-positive Critical classifications for patients whose weight gain is explained by benign causes (post-holiday sodium intake, etc.).

---

#### Change 2: Escalation modifier rule (F-T1)

**Failure observed:** No mechanism existed to escalate urgency when a contextual high-risk factor (like an allergy conflict) was known at triage time. The allergy conflict in Scenario 3 (NSAID allergy + patient using NSAIDs) was not visible to the Triage Agent because it had not yet queried the EHR — yet it significantly changes the risk profile.

**Before (v1):** No escalation modifiers.

**After (v2):**
```
ESCALATION MODIFIER: If the alert involves a patient with a documented ALLERGY to the substance or medication class implicated in the alert context, upgrade urgency by one level regardless of the raw values.
```

And new output field:
```json
"escalation_modifiers_applied": ["list or empty array"]
```

**Rationale:** The escalation modifier creates an explicit, auditable trail for why urgency was upgraded. The orchestrator can read `escalation_modifiers_applied` to understand decisions without re-running the agent. Note: this modifier only activates when the allergy is already known at triage time — for newly discovered allergy conflicts, the Synthesis Agent handles escalation in the CCB.

---

#### Change 3: Dynamic time window (F-T2)

**Failure observed:** The EHR time window was hardcoded to 6 months in all v1 few-shot examples. For chronic conditions like heart failure, 6 months is insufficient — the patient's entire HF history (onset, hospitalisations, weight thresholds) may go back years and is essential context.

**Before (v1):**
```
"time_window_months": 6  (hardcoded in all examples)
```

**After (v2):**
```
DYNAMIC TIME WINDOW:
- Critical: 24 months
- Urgent: 12 months
- Routine: 6 months
- Informational: 3 months
For patients with chronic conditions (heart failure, CKD), add 6 months to these defaults.
```

**Rationale:** The time window is itself a clinically meaningful parameter — it determines how much historical context the EHR agent retrieves. A shorter window saves tokens and latency; a longer window catches older events. The urgency-based scaling is appropriate because more urgent alerts require more context to safely evaluate. The chronic condition modifier is a rule of thumb that future iterations could make more precise using ICD-10 code lookups.

---

#### Change 4: Multi-measurement alert handling (F-T3)

**Failure observed:** In Scenario 1 (PT001, systolic 162 + diastolic 104), the alert input included both measurements, but the triage query only referenced "elevated BP" without specifying that both components breached threshold simultaneously. Bilateral threshold breach carries different clinical significance than a unilateral breach.

**Before (v1):** No multi-measurement instruction.

**After (v2):**
```
MULTI-MEASUREMENT ALERTS: When both components of a paired measurement breach threshold simultaneously, classify based on the HIGHER-severity component and note both breaches in the urgency_rationale.
```

**Rationale:** This is a specific clinical knowledge injection — blood pressure is a paired measurement (systolic + diastolic) and the clinical significance of combined breaches is not the same as a single breach. The instruction is narrow enough to not over-generalise.

---

## Part 3: EHR Retrieval Agent — Full Iteration History

### 3.1 Design Rationale (v1)

**Core challenge:** The EHR retrieval agent must extract facts from unstructured documents without adding clinical interpretation. The main failure mode in RAG-based clinical systems is hallucination — the model "remembers" clinical facts from training and presents them as if they were retrieved from the patient's records.

**Key design decisions:**

**Anti-hallucination as priority #1:** The phrase "CRITICAL RULE: You must only report information that is present in the retrieved EHR documents" is placed before the extraction priorities, not after. Placement matters — instructions at the beginning of a system prompt receive more weight than instructions at the end.

**Extraction priority order:** Allergy alerts are listed first because they are the highest-safety-risk finding. A missed allergy conflict can cause direct patient harm. The ordering (allergy → medications → diagnoses → labs → notes → missing data) reflects a deliberate clinical triage of information importance.

**Negative example for hallucination:** The v1 prompt included an explicit "WRONG vs CORRECT" example showing a hallucinated medication entry. This is one of the most effective anti-hallucination techniques — showing the model what a hallucination looks like and labelling it as wrong is more reliable than abstract instructions alone.

**RAG configuration rationale:**
- Top-k = 8: Sufficient to cover all EHR sections for one patient (demographics, problem list, medications, labs, visit notes per date) without over-retrieving
- Similarity threshold = 0.70: High enough to exclude weakly-relevant chunks, low enough to capture all sections for the target patient
- Semantic chunking by section: Prevents medication lists from mixing with visit notes in the same chunk — preserves the clinical meaning of each section type

---

### 3.2 v1 → v2 Changes: Before/After Comparison

#### Change 1: Pattern flags field (F-E1)

**Failure observed:** In Scenario 5 (Kemal Aydın), the EHR contained both a sub-therapeutic Metoprolol level AND elevated GGT and ALT. These two findings together form a clinically notable pattern suggesting possible alcohol-mediated medication non-adherence. In v1, they were reported as separate, unrelated lab values. The Synthesis Agent could in principle connect them, but only if it noticed the co-occurrence across separate JSON fields.

**Before (v1):** Labs reported as separate facts only.

**After (v2):**
```json
"pattern_flags": [
  {
    "pattern": "Sub-therapeutic Metoprolol level (28 ng/mL) co-occurring with elevated GGT (112 U/L) and ALT (58 U/L)",
    "findings": ["Metoprolol plasma level: 28 ng/mL (L)", "GGT: 112 U/L (H)", "ALT: 58 U/L (H)"],
    "note": "Pattern flagged for clinician attention — clinical significance to be determined by physician"
  }
]
```

**Rationale:** The `pattern_flags` field gives the EHR agent a mechanism to surface notable co-occurrences without interpreting them clinically. The note field ("clinical significance to be determined by physician") is essential — it prevents the pattern flag from becoming a diagnosis. This is a concrete example of providing more structured output without overstepping the agent's role boundary.

**Important constraint added:** "Do not interpret — just note the co-occurrence" prevents the agent from concluding "this pattern suggests alcohol use disorder" — that leap belongs to the Synthesis Agent or the clinician.

---

#### Change 2: Staleness rule (F-E2)

**Failure observed:** In Scenario 1, a creatinine from April 2026 was included without any staleness warning. When the synthesis agent recommended ARB initiation, the CCB cited this as supporting evidence — but the lab was 52 days old at the time of the alert. A clinician acting on this without rechecking could miss an interim renal function change.

**Before (v1):** Labs reported as-is regardless of age.

**After (v2):**
```
STALENESS RULE: Any lab result dated more than 90 days before today's date must have "[POTENTIALLY OUTDATED — X days since collection]" appended to the flag field.
```

**Before:**
```json
{"test": "Serum Creatinine", "value": 1.1, "unit": "mg/dL", "date": "2026-04-10", "flag": "normal"}
```

**After:**
```json
{"test": "Serum Creatinine", "value": 1.1, "unit": "mg/dL", "date": "2026-04-10", "flag": "normal [POTENTIALLY OUTDATED — 52 days since collection]"}
```

**Rationale:** The staleness warning is injected at the Python layer (not by the LLM) using `_check_staleness()` in `ehr_retrieval_agent.py`. This is a deliberate architectural choice — it is more reliable to compute date arithmetic in Python than to instruct an LLM to do so (models frequently make date calculation errors). The 90-day threshold is a conservative clinical standard; some specialties use shorter windows (30 days for electrolytes in CKD patients, for example).

---

#### Change 3: Confidence scoring rubric (F-E3)

**Failure observed:** In Scenario 4 (Elif Şahin, sparse EHR), the retrieval_confidence was returned as 0.3 but no instruction existed about what downstream agents should do with this. The Synthesis Agent proceeded as if the EHR were fully reliable.

**Before (v1):** Confidence was a free-form float with no rubric or downstream guidance.

**After (v2):**
```
CONFIDENCE SCORING RUBRIC:
- 0.9–1.0: Comprehensive records; all query parameters answered; no major gaps
- 0.7–0.89: Good records; most parameters answered; 1-2 minor gaps
- 0.5–0.69: Moderate records; several gaps; proceed with caution
- 0.3–0.49: Sparse records; significant gaps
- 0.0–0.29: Minimal records; almost no relevant data

When confidence is below 0.5, add "LOW EHR CONFIDENCE — synthesis will rely heavily on anamnesis data" to missing_data_flags.
```

**Rationale:** The rubric serves two functions. First, it standardises how the agent calibrates the confidence score — without a rubric, the score is subjective and inconsistent across runs. Second, the mandatory flag at <0.5 gives the Synthesis Agent an explicit signal that it must weight the anamnesis data more heavily. This creates a graceful degradation pathway for sparse EHR scenarios.

---

## Part 4: Anamnesis Agent — Full Iteration History

### 4.1 Design Rationale (v1)

**Core challenge:** The anamnesis agent must translate colloquial patient language into structured clinical observations without over-interpreting. Two failure modes pull in opposite directions: under-extraction (missing important patient-reported information) and over-interpretation (adding medical conclusions the patient did not express).

**Key design decisions:**

**"Translate, do not interpret clinically" as Core Principle #1:** This principle is stated first and demonstrated with an explicit example. The example format (Patient says → You report → You do NOT say) is more effective than abstract instructions because it shows the exact linguistic transformation expected.

**Sensitivity guardrails as explicit categories:** Rather than a general "be sensitive" instruction, four specific categories are named (mental health, substance use, domestic, reluctance) with specific handling rules for each. Specific categories prevent the model from applying a one-size-fits-all tone to genuinely different situations.

**`adherence_confidence` as categorical, not numeric:** A 4-value categorical (High / Medium / Low / Unknown) was chosen over a numeric score because medication adherence confidence is fundamentally a qualitative clinical judgment. A clinician reading "Low adherence confidence" understands the implication immediately; a reading of "0.3" does not communicate the same information.

---

### 4.2 v1 → v2 Changes: Before/After Comparison

#### Change 1: Caregiver vs. patient reporting (F-A1)

**Failure observed:** Scenario 9 involved Raymond Castillo (Alzheimer's patient) whose anamnesis was reported by his daughter/caregiver. The v1 output attributed all statements directly to the patient: "Patient reports full medication adherence." In reality, the caregiver was reporting, and caregiver-reported adherence has different reliability than patient-reported adherence.

**Before (v1):** No caregiver distinction. Output format had no `reporter_type` field.

**After (v2):**
```
CAREGIVER VS. PATIENT REPORTING:
If reported by a caregiver:
- Note in medication_adherence_summary: "Note: information reported by caregiver [relationship], not directly by patient"
- Set reporter_type to "caregiver"
- Set adherence_confidence to maximum "Medium"
- Add "caregiver_reported" to sensitivity_flags
```

New output field: `"reporter_type": "patient | caregiver | unknown"`

**Rationale:** The adherence confidence cap at Medium for caregiver reports reflects a genuine epistemic limitation — a caregiver can confirm that they administered the medication, but cannot confirm the patient's subjective experience or whether the patient secretly disposed of the medication. This is a clinical knowledge injection that makes the output more accurate about what is actually known.

---

#### Change 2: Defensive language flag (F-A2)

**Failure observed:** In Scenario 5 (Kemal Aydın), the patient said "I take it every single morning, I never miss it." The v1 Anamnesis Agent set adherence_confidence to "High" based on the strength of the patient's claim. However, emphatically emphatic denial is a recognised behavioural pattern associated with adherence anxiety, stigma, or non-adherence — not necessarily with confirmed adherence.

**Before (v1):** Emphatic statement → High adherence confidence.

**After (v2):**
```
DEFENSIVE LANGUAGE FLAG:
If the patient uses emphatic or defensive language about adherence (e.g., "I always take it, I promise", "I never miss it", "I swear I took it"):
- Note: "Patient used notably emphatic language regarding adherence" in medication_adherence_summary
- Set adherence_confidence to "Medium" rather than "High"
```

**Rationale:** This is a subtle but important distinction. The rule does not accuse the patient of lying — it simply notes that emphatically defensive language is a different signal than calm confirmation of adherence, and should not produce the same confidence level. The phrasing "notably emphatic language" is chosen to be factual and non-judgmental. The Synthesis Agent then uses the Medium confidence combined with the sub-therapeutic lab levels to flag the discrepancy.

---

#### Change 3: ISO date standardisation (F-A3)

**Failure observed:** Symptom diary entries used inconsistent date formats ("May 28", "28/05", "2026-05-28") across different patients. The Synthesis Agent's timeline narrative became confused when mixing EHR dates (ISO format) with anamnesis diary dates (mixed formats).

**Before (v1):** Free-form dates in symptom_timeline.

**After (v2):** `"All dates in symptom_timeline use ISO format YYYY-MM-DD"` added to Core Principle #4.

**Rationale:** Date standardisation is a data quality issue, not a clinical reasoning issue. The LLM can parse natural language dates ("May 28") into ISO format — instructing it to do so consistently costs virtually nothing but significantly improves downstream data quality. This is a simple instruction with disproportionate impact.

---

## Part 5: Synthesis Agent — Full Iteration History

### 5.1 Design Rationale (v1)

**Core challenge:** The Synthesis Agent is the most complex prompt in the system because it must (a) reason across three heterogeneous data sources, (b) produce a clinically appropriate narrative, (c) avoid diagnoses, (d) maintain source traceability, and (e) calibrate its own uncertainty. Each of these requirements could conflict with the others.

**Key design decisions:**

**Source citation requirement as Critical Rule #1:** "(EHR), (RPM), or (Anamnesis)" tagging was placed as the first Critical Rule because traceability is the foundation of a trustworthy clinical brief. Without traceability, there is no way to audit the CCB or distinguish synthesised reasoning from hallucination.

**The "never diagnose" constraint with concrete language substitutes:** Rather than just saying "don't diagnose", the v1 prompt provided replacement language ("findings are consistent with", "may suggest", "warrants evaluation for"). This is more effective than prohibitions alone because it gives the model safe alternatives rather than leaving a linguistic void.

**`conflicts_detected` as a dedicated field:** Early prototyping showed that when source conflicts existed and were not explicitly surfaced, the model would silently resolve them by favouring one source. A dedicated field forces the model to acknowledge conflicts explicitly rather than hiding them.

**Negative example format:** The "WRONG → CORRECT" pair in v1 demonstrates prohibited language ("hypertensive urgency", "should be admitted") side by side with appropriate alternatives. This dual example format is more effective than either a positive or negative example alone.

---

### 5.2 v1 → v2 Changes: Before/After Comparison

#### Change 1: Safety-first allergy rule (F-S1)

**Failure observed:** In Scenario 3, the NSAID allergy conflict was mentioned in `contextual_analysis.contributing_factors` but the `patient_snapshot.data_quality_warning` field was null. A clinician reading a CCB would typically read the patient snapshot first — if the allergy conflict is only in the body of the analysis, it could easily be missed.

**Before (v1):** Allergy conflict mentioned once in contextual_analysis.

**After (v2):**
```
SAFETY-FIRST RULE:
Any allergy conflict must appear in:
1. patient_snapshot.data_quality_warning — first (where clinician looks first)
2. contextual_analysis.contributing_factors — with full citation
3. recommended_actions — as the FIRST action
An allergy conflict anywhere other than all three locations is a safety failure.
```

**Rationale:** Clinical safety information should be redundant — critical alerts should appear in multiple places so they cannot be missed regardless of reading order. The "safety failure" language was chosen deliberately to elevate the severity of non-compliance with this rule in the model's reasoning.

---

#### Change 2: Urgency-appropriate actions (F-S2)

**Failure observed:** In Scenario 2 (False Alarm, Informational urgency), the v1 Synthesis Agent generated two recommended actions including "consider monitoring glucose more frequently." This is not inappropriate advice, but for an Informational alert it creates unnecessary noise — the clinician's attention should not be captured by follow-up recommendations when the alert requires no action.

**Before (v1):** No urgency-specific guidance on recommended_actions length or content.

**After (v2):**
```
URGENCY-APPROPRIATE RECOMMENDED ACTIONS:
- CRITICAL: Focus on immediate escalation
- URGENT: 2-4 specific, ordered, actionable steps
- ROUTINE: 1-2 follow-up steps; no urgent language
- INFORMATIONAL: 0-1 monitoring steps; explicitly state "No immediate action required for this alert"
```

**Rationale:** Matching the number and tone of recommended actions to the urgency level prevents the CCB from being interpreted as more or less urgent than it is. An Informational CCB with three recommended actions reads as more concerning than intended.

---

#### Change 3: Confidence score rubric (F-S4)

**Failure observed:** v1 confidence_scores varied widely for similar scenarios — ranging from 0.62 to 0.91 for comparable data quality. Without a rubric, the score was essentially a free-form expression of the model's subjective assessment.

**Before (v1):** Confidence score described as "0.0-1.0" with no calculation method.

**After (v2):**
```
CONFIDENCE SCORE RUBRIC:
Start at 0.5
+0.2 if EHR retrieval_confidence >= 0.8
+0.1 if EHR retrieval_confidence >= 0.6
+0.15 if anamnesis adherence_confidence is "High"
+0.05 if anamnesis adherence_confidence is "Medium"
-0.2 if any conflicts_detected between sources
-0.1 for each missing_data_flag that directly affects the primary finding
-0.15 if EHR retrieval_confidence < 0.5
Maximum: 0.95. Minimum: 0.10.
```

**Rationale:** The arithmetic rubric makes the confidence score deterministic and interpretable. A CCB with EHR confidence 0.85, high anamnesis confidence, no conflicts, and one relevant missing flag would score: 0.5 + 0.2 + 0.15 - 0.1 = 0.75 — which accurately reflects "strong data with one notable gap". The 0.95 maximum reflects the epistemological principle that uncertainty always exists in clinical contexts.

---

## Part 6: Lessons Learned

### Lesson 1: Role definition + explicit limit > role definition alone
Every effective agent prompt opens with role grant followed by explicit limit. "You are X. You are NOT Y." This pattern is more effective than either statement alone because it closes the ambiguity about where the agent's authority ends.

### Lesson 2: Anti-hallucination rules need negative examples
Abstract instructions ("do not hallucinate") are insufficient. Showing the model what a hallucination looks like and labelling it explicitly ("❌ WRONG — this medication was not in the retrieved chunks") is more effective at suppressing confabulation.

### Lesson 3: Safety-critical information should be redundant
The three-location allergy rule learned from Scenario 3 reflects a principle from human factors engineering: safety-critical information should appear in more than one place so it cannot be missed regardless of reading order.

### Lesson 4: Output schema precision prevents downstream parsing failures
Inconsistent output schemas (mixed date formats, missing fields, varied nesting) caused silent failures in the orchestrator. Adding ISO date enforcement, field defaults, and explicit "null" values for optional fields resolved most integration failures without any prompt changes to downstream agents.

### Lesson 5: Temperature tuning is meaningful in clinical applications
Temperature 0.0 for classification tasks (triage) vs 0.3 for interpretation tasks (anamnesis) produced meaningfully different outputs. At temperature 0.0, the anamnesis agent produced overly literal paraphrases that lost nuance. At temperature 0.3, the triage agent occasionally produced different urgency levels for identical inputs. Matching temperature to task type is not a trivial detail.

### Lesson 6: Python-layer post-processing is more reliable than LLM-layer computation
Date arithmetic (staleness detection) and schema validation (disclaimer check, confidence clamping) were moved to the Python orchestration layer rather than relying on LLM compliance. LLMs make frequent arithmetic errors on date calculations. Python does not.

---

## Part 7: v3 Prompt Plans (Week 4 Integration Testing)

Based on integration testing in Week 4, the following improvements are planned for v3:

| Agent | Planned Change | Trigger |
|---|---|---|
| Triage | Add ICD-10 code lookup to dynamic time window rule | HF patients sometimes have multiple ICD-10 codes; lookup ensures correct time window |
| EHR Retrieval | Add instruction for conflicting visit note medication doses | v2 reports both — but does not note which is more recent |
| Anamnesis | Add instruction for telephone/portal reported anamnesis vs in-person | Data source reliability differs |
| Synthesis | Refine differential_considerations to require ordered likelihood with probability language | v2 lists differentials but does not explicitly order by likelihood |
| Synthesis | Add "escalation_recommendation" field for Critical scenarios bypassed by escalation pathway | Currently only urgency + disclaimer returned for Critical escalations |

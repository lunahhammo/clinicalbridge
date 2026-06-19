"""
evaluation/test_scenarios.py
Evaluation harness for ClinicalBridge.

Scores CCB outputs against gold-standard Clinical Context Briefs across all
5 scenarios. Produces a machine-readable results JSON and a human-readable
summary report.

Usage:
    python evaluation/test_scenarios.py --mock    # Run with mock outputs (no API needed)
    python evaluation/test_scenarios.py --live    # Run full pipeline (requires API key)
"""

import json
import argparse
import sys
from pathlib import Path
from datetime import datetime


# ── Scoring functions ─────────────────────────────────────────────────────────

def score_urgency(produced: str, expected: str) -> dict:
    """Score triage urgency classification."""
    correct = produced == expected
    return {
        "metric":   "urgency_classification",
        "expected": expected,
        "produced": produced,
        "score":    1.0 if correct else 0.0,
        "pass":     correct,
    }

def score_disclaimer_present(ccb: dict) -> dict:
    """Check that mandatory disclaimer is present and non-empty."""
    disclaimer = ccb.get("disclaimer", "")
    present    = bool(disclaimer) and len(disclaimer) > 50
    return {
        "metric":  "disclaimer_present",
        "score":   1.0 if present else 0.0,
        "pass":    present,
        "detail":  "Present" if present else "MISSING or too short",
    }

def score_allergy_flag(ccb: dict, scenario_has_allergy_conflict: bool) -> dict:
    """For scenarios with allergy conflicts, check it appears in data_quality_warning."""
    if not scenario_has_allergy_conflict:
        return {"metric": "allergy_flag", "score": 1.0, "pass": True, "detail": "Not applicable"}

    warning = ccb.get("patient_snapshot", {}).get("data_quality_warning", "") or ""
    present = any(kw in warning.upper() for kw in ["ALLERGY", "NSAID", "IBUPROFEN"])
    return {
        "metric":  "allergy_in_data_quality_warning",
        "score":   1.0 if present else 0.0,
        "pass":    present,
        "detail":  "Allergy conflict present in warning" if present else "ALLERGY CONFLICT MISSING from data_quality_warning",
    }

def score_recommended_actions(ccb: dict, expected_actions: list[str]) -> dict:
    """Check that expected key actions are present in recommended_actions."""
    produced_text = " ".join(
        a.get("action", "").lower()
        for a in ccb.get("recommended_actions", [])
    )
    found     = [kw for kw in expected_actions if kw.lower() in produced_text]
    not_found = [kw for kw in expected_actions if kw.lower() not in produced_text]
    score     = len(found) / len(expected_actions) if expected_actions else 1.0

    return {
        "metric":    "recommended_actions_completeness",
        "expected":  expected_actions,
        "found":     found,
        "not_found": not_found,
        "score":     round(score, 2),
        "pass":      score >= 0.75,
    }

def score_conflicts_detected(ccb: dict, should_have_conflict: bool) -> dict:
    """Check that source conflicts are flagged when expected."""
    conflicts = ccb.get("contextual_analysis", {}).get("conflicts_detected", [])
    has       = len(conflicts) > 0

    if should_have_conflict:
        return {
            "metric":  "conflicts_detected",
            "score":   1.0 if has else 0.0,
            "pass":    has,
            "detail":  f"{len(conflicts)} conflict(s) flagged" if has else "Expected conflict NOT flagged",
        }
    else:
        return {
            "metric":  "conflicts_detected",
            "score":   1.0,
            "pass":    True,
            "detail":  "No conflict expected — not scored",
        }

def score_source_citations(ccb: dict) -> dict:
    """Check that contextual analysis cites sources."""
    analysis_text = json.dumps(ccb.get("contextual_analysis", {}))
    citations     = sum(1 for tag in ["(EHR)", "(RPM)", "(Anamnesis)"] if tag in analysis_text)
    has_citations = citations >= 2
    return {
        "metric":  "source_citations_present",
        "score":   1.0 if has_citations else 0.5,
        "pass":    has_citations,
        "detail":  f"{citations} source tag(s) found in contextual_analysis",
    }

def score_confidence_in_bounds(ccb: dict) -> dict:
    """Check confidence score is within valid bounds."""
    score = ccb.get("confidence_score", -1)
    valid = isinstance(score, (int, float)) and 0.10 <= score <= 0.95
    return {
        "metric":  "confidence_score_valid",
        "score":   1.0 if valid else 0.0,
        "pass":    valid,
        "detail":  f"confidence_score = {score}",
    }

def score_no_diagnostic_language(ccb: dict) -> dict:
    """Check CCB does not contain diagnostic declarations."""
    forbidden = [
        "the patient has hypertensive urgency",
        "the patient is in acute decompensation",
        "diagnosis:",
        "should be admitted",
        "this is a case of",
        "the patient has heart failure exacerbation",
    ]
    ccb_text = json.dumps(ccb).lower()
    violations = [p for p in forbidden if p in ccb_text]
    clean = len(violations) == 0
    return {
        "metric":     "no_diagnostic_language",
        "score":      1.0 if clean else 0.0,
        "pass":       clean,
        "violations": violations,
    }


# ── Mock CCB outputs (representative of v2 system performance) ────────────────

def get_mock_ccb(scenario_num: int) -> dict:
    """
    Return representative mock CCB for each scenario.
    These simulate the v2 system's actual output for evaluation purposes.
    """
    base_disclaimer = (
        "This Clinical Context Brief is a decision-support summary generated by an AI "
        "prototype using simulated data. It does not constitute a diagnosis or treatment "
        "order. All clinical decisions require review and approval by a qualified physician. "
        "This system is not approved for use in real patient care."
    )

    scenarios = {
        1: {
            "patient_id": "PT001",
            "generated_at": "2026-06-02T10:12:00",
            "alert_summary": {
                "trigger": "Systolic BP 162 mmHg (threshold 155 mmHg) over 3 consecutive days per RPM",
                "urgency_classification": "Urgent",
                "rationale": "Sustained Stage 2 hypertension over 3 days in a diabetic patient with family history of stroke.",
            },
            "patient_snapshot": {
                "name": "Mehmet Yıldız, 67M",
                "active_conditions": ["Essential hypertension (I10)", "Type 2 diabetes mellitus (E11.9)"],
                "current_treatment_plan": "Lisinopril 10mg daily (prescribed), Metformin 500mg BID, Aspirin 81mg daily",
                "data_quality_warning": "NOTE: Patient self-reports discontinuing Lisinopril ~10 days ago (Anamnesis). EHR medication list does not reflect this change. Effective antihypertensive coverage may be zero.",
            },
            "contextual_analysis": {
                "primary_finding": "The sustained BP elevation is most likely explained by the patient's self-discontinuation of Lisinopril approximately 10 days ago (Anamnesis), temporally consistent with the RPM trend showing BP rising from 142–145 mmHg to 162–165 mmHg (RPM). A persistent dry cough — documented at two prior clinic visits without being addressed — was cited as the reason for discontinuation (EHR: 2025-11-20, 2026-04-10).",
                "contributing_factors": [
                    "Lisinopril self-discontinued ~10 days ago due to dry cough (Anamnesis) — cough documented but unaddressed at prior visits (EHR)",
                    "Ibuprofen 400mg taken for headaches over past 3 days (Anamnesis) — NSAIDs reduce antihypertensive efficacy",
                    "High-sodium diet acknowledged by patient (Anamnesis)",
                    "Family history: father stroke age 71, brother MI age 58 (Anamnesis)",
                ],
                "conflicts_detected": [
                    "EHR shows Lisinopril as active prescribed medication; Anamnesis reveals patient self-discontinued it — EHR medication list does not reflect actual intake (Anamnesis vs EHR)"
                ],
                "timeline": "BP was stable at 142–145 mmHg through recent visits (EHR). Following Lisinopril self-discontinuation (~May 22, Anamnesis), RPM shows gradual rise to 162–165 mmHg over 10 days. Ibuprofen use commenced 3 days ago (Anamnesis), potentially compounding BP elevation.",
            },
            "risk_assessment": {
                "immediate_risks": "Sustained Stage 2 hypertension with symptomatic headaches and dizziness. Concurrent ibuprofen use adds nephrotoxicity risk in a diabetic patient.",
                "medium_term_risks": "Family history of stroke and MI at similar age. Suboptimal BP control with diabetes significantly increases cardiovascular and cerebrovascular risk.",
                "differential_considerations": "Most likely: ACE inhibitor self-discontinuation (Anamnesis) with NSAID compounding effect. Also possible: dietary sodium increase (Anamnesis — acknowledged high-sodium diet). Less likely: new secondary hypertension cause (no supporting data in either source).",
            },
            "recommended_actions": [
                {"action": "Consider switching to an ARB (e.g., Losartan, Valsartan) — equivalent BP efficacy without cough side effect", "confidence": "High", "evidence": "ACE inhibitor cough documented at 2 EHR visits + patient confirmed cough as reason for stopping (Anamnesis)"},
                {"action": "Advise immediate cessation of ibuprofen — paracetamol is an appropriate alternative for headaches", "confidence": "High", "evidence": "NSAID use confirmed (Anamnesis); contraindicated with hypertension and diabetes"},
                {"action": "Same-day or next-day clinical contact to initiate medication transition", "confidence": "High", "evidence": "Sustained Stage 2 HTN over 3 days with symptomatic headaches (RPM + Anamnesis)"},
            ],
            "uncertainties_and_gaps": [
                "Exact Lisinopril stop date is patient-estimated — not independently verifiable from EHR",
                "No renal labs since April 2026 — creatinine and potassium needed before ARB initiation (EHR)",
            ],
            "confidence_score": 0.87,
            "disclaimer": base_disclaimer,
        },
        2: {
            "patient_id": "PT002",
            "generated_at": "2026-06-02T10:28:00",
            "alert_summary": {
                "trigger": "Blood glucose 218 mg/dL (threshold 200 mg/dL) on 2026-06-01 post-breakfast",
                "urgency_classification": "Informational",
                "rationale": "Glucose alert contextually explained by supervised low-carbohydrate dietary intervention documented in EHR and confirmed by patient.",
            },
            "patient_snapshot": {
                "name": "Ayşe Kaya, 54F",
                "active_conditions": ["Type 2 diabetes mellitus (E11.65)", "Hyperlipidemia (E78.5)"],
                "current_treatment_plan": "Metformin 1000mg BID, Glipizide 5mg daily, Atorvastatin 20mg at bedtime",
                "data_quality_warning": None,
            },
            "contextual_analysis": {
                "primary_finding": "The glucose alert is contextually explained by a supervised low-carbohydrate dietary program initiated on 2026-05-26 (Anamnesis), explicitly documented in the EHR clinic visit of 2026-03-15 where the physician noted glucose values may vary during the transition period (EHR). Post-prandial spikes are an expected feature of the early dietary adaptation phase.",
                "contributing_factors": [
                    "Supervised low-carb dietary program started 2026-05-26 (Anamnesis) — documented and anticipated by physician (EHR)",
                    "Post-prandial pattern consistent with dietary carbohydrate transition (RPM trend analysis)",
                    "Full medication adherence confirmed — no medication contribution (Anamnesis)",
                ],
                "conflicts_detected": [],
                "timeline": "Pre-dietary-change baseline glucose 148–155 mg/dL (RPM). Since program start (May 26), post-prandial spikes to 204–218 mg/dL with fasting values remaining lower (142 mg/dL at 06:00, RPM). Pattern consistent with dietary adaptation.",
            },
            "risk_assessment": {
                "immediate_risks": "Low. No symptoms of acute hyperglycaemia reported (Anamnesis). Values, while elevated, are not in the dangerous range for Type 2 DM.",
                "medium_term_risks": "Monitor HbA1c in 8–12 weeks to assess dietary intervention impact.",
                "differential_considerations": "Most likely: expected post-prandial glucose elevation during low-carb dietary adaptation (EHR + Anamnesis concordant). Also possible: dietary non-compliance creating erratic glucose (less likely — Anamnesis confirms adherence). Less likely: medication failure (contradicted by full adherence confirmation).",
            },
            "recommended_actions": [
                {"action": "No immediate action required for this alert — alert is contextually explained by supervised dietary intervention", "confidence": "High", "evidence": "EHR physician documentation of anticipated glucose variation + Anamnesis full adherence confirmation"},
            ],
            "uncertainties_and_gaps": [
                "Nutritionist intake records not available in EHR — dietary program details from anamnesis only",
            ],
            "confidence_score": 0.91,
            "disclaimer": base_disclaimer,
        },
        3: {
            "patient_id": "PT003",
            "generated_at": "2026-06-02T10:35:00",
            "alert_summary": {
                "trigger": "Body weight 91.2 kg — 6.2 kg gain over 13 days (baseline 85 kg, threshold 87 kg)",
                "urgency_classification": "Critical",
                "rationale": "6.2 kg weight gain over 13 days in a documented heart failure patient with self-reported ankle oedema and exertional dyspnoea meets Critical threshold. NSAID allergy conflict identified.",
            },
            "patient_snapshot": {
                "name": "Hasan Demir, 75M",
                "active_conditions": ["Heart failure (I50.9)", "Essential hypertension (I10)", "Atrial fibrillation (I48.91)"],
                "current_treatment_plan": "Furosemide 40mg daily, Carvedilol 6.25mg BID, Lisinopril 5mg daily, Apixaban 5mg BID",
                "data_quality_warning": "⚠️ ALLERGY CONFLICT: Patient self-reports taking ibuprofen 2-3 times this week (Anamnesis). EHR documents SEVERE NSAID allergy: reaction is fluid retention and worsening heart failure. This is a direct allergy violation and is a likely contributor to current fluid overload.",
            },
            "contextual_analysis": {
                "primary_finding": "Progressive fluid retention findings consistent with acute heart failure decompensation (RPM weight trend). The continuous 13-day weight gain trajectory (0.47 kg/day average, RPM) combined with bilateral ankle oedema and new exertional dyspnoea (Anamnesis) indicates clinically significant fluid accumulation. The concurrent NSAID allergy violation (EHR allergy + Anamnesis OTC report) is a likely direct contributor to fluid retention.",
                "contributing_factors": [
                    "⚠️ ALLERGY CONFLICT: Ibuprofen use 2-3 times this week (Anamnesis) — NSAID allergy documented as causing fluid retention and worsening HF (EHR)",
                    "Progressive weight gain 6.2 kg over 13 days with no plateau (RPM)",
                    "Bilateral ankle oedema worsening over the past week (Anamnesis)",
                    "New exertional dyspnoea on stairs over past 3-4 days (Anamnesis)",
                    "BNP already elevated at 420 pg/mL at last visit 2026-05-01 (EHR) — pre-existing elevated baseline",
                    "High-sodium restaurant meal approximately 10 days ago — temporally coincides with onset of weight gain (Anamnesis)",
                ],
                "conflicts_detected": [],
                "timeline": "Baseline weight 85 kg (EHR May 2026). Weight gain begins approximately 2026-05-20 per RPM, coinciding with patient's reported restaurant meal and onset of ibuprofen use. Progressive daily gain documented in RPM. Ankle swelling noticed by patient by May 24, worsening through June 1 (Anamnesis symptom diary).",
            },
            "risk_assessment": {
                "immediate_risks": "Acute heart failure decompensation findings. NSAID allergy violation is ongoing. Apixaban active — anticoagulation relevant to clinical management decisions.",
                "medium_term_risks": "Renal function at risk — creatinine already 1.4 mg/dL (EHR), above normal; diuretic adjustment requires safe renal monitoring.",
                "differential_considerations": "Most likely: acute HF decompensation driven by NSAID allergy violation (fluid retention) + dietary sodium + baseline elevated BNP (EHR + Anamnesis concordant). Also possible: isolated dietary sodium contribution without NSAID component (less likely — NSAID allergy mechanism specifically causes fluid retention). Less likely: other cause of weight gain (contradicted by concurrent cardiac symptoms).",
            },
            "recommended_actions": [
                {"action": "Immediate cessation of ibuprofen — NSAID ALLERGY VIOLATION (EHR: severe allergy documented; reaction: fluid retention and worsening HF)", "confidence": "High", "evidence": "EHR allergy record + Anamnesis OTC ibuprofen use confirmed"},
                {"action": "Urgent same-day clinical assessment — patient should be seen today", "confidence": "High", "evidence": "6.2 kg weight gain, ankle oedema, new exertional dyspnoea, NSAID allergy violation (RPM + Anamnesis)"},
                {"action": "Urgent labs: BNP, renal panel (creatinine, BUN, electrolytes)", "confidence": "High", "evidence": "Baseline creatinine elevated (EHR); diuretic adjustment requires renal monitoring"},
                {"action": "Consider Furosemide dose adjustment — clinician decision pending renal function results", "confidence": "Moderate", "evidence": "Current 40mg dose may be insufficient given degree of fluid overload; renal function must be verified first (EHR creatinine 1.4 mg/dL)"},
            ],
            "uncertainties_and_gaps": [
                "Ibuprofen use frequency patient-reported ('2-3 times over past week') — exact dosing unconfirmed",
                "No BNP measurement since 2026-05-01 — current level unknown",
                "SpO2 reading 95% on 2026-06-01 is borderline — trend data would be valuable",
            ],
            "confidence_score": 0.82,
            "disclaimer": base_disclaimer,
        },
        4: {
            "patient_id": "PT004",
            "generated_at": "2026-06-02T10:51:00",
            "alert_summary": {
                "trigger": "Systolic BP 168 mmHg (threshold 155 mmHg) over 4 consecutive days",
                "urgency_classification": "Urgent",
                "rationale": "Sustained Stage 2 hypertension over 4 days. EHR is critically sparse — multiple contributing factors identified from anamnesis.",
            },
            "patient_snapshot": {
                "name": "Elif Şahin, 60F",
                "active_conditions": ["Essential hypertension (I10) — onset 2023, possibly longer"],
                "current_treatment_plan": "Amlodipine 5mg once daily",
                "data_quality_warning": "EHR CRITICALLY INCOMPLETE — patient transferred from external facility 2.5 years ago; full prior records not received. Conclusions rely heavily on anamnesis data. Prior cardiovascular history, allergy history, and complete medication history unknown.",
            },
            "contextual_analysis": {
                "primary_finding": "BP elevation has multiple identifiable contributing factors from anamnesis in the absence of EHR context. Pseudoephedrine-based decongestant (OTC, 5-day use, Anamnesis) is the most likely primary contributor — sympathomimetics cause dose-dependent BP elevation. Concurrent psychosocial stress and sleep disruption (Anamnesis) are additional contributors.",
                "contributing_factors": [
                    "OTC pseudoephedrine decongestant — 5-day use temporally correlated with BP elevation onset (Anamnesis)",
                    "Significant psychosocial stress: caretaking ill parent (Anamnesis)",
                    "Poor sleep for 1 week — sympathetic activation (Anamnesis)",
                    "Amlodipine adherence confirmed (Anamnesis)",
                ],
                "conflicts_detected": [],
                "timeline": "BP readings normal prior to this episode per patient report. OTC cold medicine started approximately 5 days ago (Anamnesis). BP readings elevated throughout the 5-day decongestant use period (RPM).",
            },
            "risk_assessment": {
                "immediate_risks": "Stage 2 hypertension over 4 days with identifiable reversible precipitants. Incomplete EHR means unknown cardiovascular history cannot be excluded.",
                "medium_term_risks": "Amlodipine 5mg may be inadequate for baseline BP control — clinician assessment required after removing reversible factors.",
                "differential_considerations": "Most likely: pseudoephedrine-induced BP elevation (Anamnesis — temporal correlation; decongestant contraindicated in hypertension). Also possible: stress/sleep-mediated sympathetic activation (Anamnesis). Less likely: Amlodipine non-adherence (contradicted by patient report, Anamnesis).",
            },
            "recommended_actions": [
                {"action": "Advise immediate cessation of pseudoephedrine-based decongestant — sympathomimetics contraindicated in hypertension; suggest saline nasal spray alternative", "confidence": "High", "evidence": "5-day decongestant use temporally correlated with BP elevation (Anamnesis)"},
                {"action": "Clinical review in 24–48 hours to reassess BP after decongestant cessation", "confidence": "High", "evidence": "Reversible cause identified — response will guide next steps"},
            ],
            "uncertainties_and_gaps": [
                "Prior medical history, cardiovascular events, complete allergy history — all unknown (sparse EHR)",
                "Family history unknown — patient adopted, biological family history unavailable (Anamnesis)",
                "All key recommendations based heavily on anamnesis; EHR provides minimal corroboration",
            ],
            "confidence_score": 0.58,
            "disclaimer": base_disclaimer,
        },
        5: {
            "patient_id": "PT005",
            "generated_at": "2026-06-02T11:08:00",
            "alert_summary": {
                "trigger": "Systolic BP 174 mmHg (threshold 160 mmHg) over 4 consecutive days",
                "urgency_classification": "Urgent",
                "rationale": "Sustained Stage 2 hypertension despite claimed medication adherence; sub-therapeutic drug levels on objective labs represent a significant discrepancy.",
            },
            "patient_snapshot": {
                "name": "Kemal Aydın, 62M",
                "active_conditions": ["Essential hypertension (I10)", "Alcohol use disorder (F10.20)", "Hypercholesterolemia (E78.00)"],
                "current_treatment_plan": "Metoprolol succinate 50mg daily, Rosuvastatin 10mg daily",
                "data_quality_warning": None,
            },
            "contextual_analysis": {
                "primary_finding": "There is a direct conflict between the patient's stated full adherence to Metoprolol (Anamnesis) and the objective lab finding of a sub-therapeutic plasma Metoprolol level of 28 ng/mL against a therapeutic range of 50–200 ng/mL (EHR). This discrepancy is the central clinical question requiring investigation.",
                "contributing_factors": [
                    "Sub-therapeutic Metoprolol level 28 ng/mL (EHR) — below therapeutic range 50–200 ng/mL",
                    "Patient states 'I take it every single morning, I never miss it' — emphatic adherence claim (Anamnesis)",
                    "Elevated GGT 112 U/L and ALT 58 U/L (EHR) — co-occurring with sub-therapeutic drug level (EHR pattern flag)",
                    "Documented alcohol use disorder history (EHR) — patient's self-reported consumption may be underestimated (Anamnesis sensitivity flag)",
                    "Patient was defensive when asked about alcohol use (Anamnesis)",
                    "LDL 142 mg/dL elevated despite Rosuvastatin — possible second adherence concern (EHR)",
                ],
                "conflicts_detected": [
                    "Patient reports full adherence to Metoprolol (Anamnesis) — objective plasma level 28 ng/mL is sub-therapeutic (EHR). These two data points directly conflict. Possible explanations include medication non-adherence, rapid metabolism, or blood draw timing. Clinical investigation required — this system cannot resolve the conflict."
                ],
                "timeline": "Last office visit 2026-05-20 showed BP 158/96 — already elevated (EHR). Sub-therapeutic Metoprolol level measured same date (EHR). Current RPM readings 162–174 mmHg over 4 days represent worsening of an already-elevated trajectory (RPM).",
            },
            "risk_assessment": {
                "immediate_risks": "Sustained Stage 2 hypertension. Elevated liver enzymes in context of alcohol use disorder require monitoring.",
                "medium_term_risks": "Unaddressed medication non-adherence (if confirmed) leaves hypertension effectively unmanaged. Alcohol use disorder is a dose-dependent hypertensive agent.",
                "differential_considerations": "Most likely: medication non-adherence (supported by sub-therapeutic level, EHR; contradicted by patient report, Anamnesis). Also possible: underreported alcohol use reducing medication effectiveness and causing liver enzyme elevation (supported by AUD history, EHR; defensive anamnesis response). Less likely: pharmacogenomic rapid metabolism (possible but requires testing to confirm).",
            },
            "recommended_actions": [
                {"action": "Clinical conversation regarding medication adherence — non-confrontational approach recommended; do not directly accuse", "confidence": "High", "evidence": "Sub-therapeutic Metoprolol level (EHR) vs stated adherence (Anamnesis) — discrepancy requires clinical investigation"},
                {"action": "Assess alcohol use using validated screening tool (e.g. AUDIT-C) in clinical consultation", "confidence": "High", "evidence": "Documented AUD (EHR) + elevated GGT (EHR) + defensive anamnesis response (Anamnesis)"},
                {"action": "Do NOT increase Metoprolol dose before confirming adherence status", "confidence": "High", "evidence": "Dose escalation in a potentially non-adherent patient with AUD would be inappropriate and potentially unsafe"},
                {"action": "Repeat liver function tests to establish trend", "confidence": "High", "evidence": "ALT and GGT elevated on 2026-05-20 labs (EHR) — trend data required"},
            ],
            "uncertainties_and_gaps": [
                "IMPORTANT: This CCB flags a discrepancy — it does NOT determine whether the patient is adherent. That determination requires clinical judgment and direct conversation.",
                "Exact alcohol consumption unknown — self-report likely underestimate given history and defensive presentation (Anamnesis)",
                "Blood draw timing relative to last Metoprolol dose not recorded (EHR)",
            ],
            "confidence_score": 0.75,
            "disclaimer": base_disclaimer,
        },
    }
    return scenarios.get(scenario_num, {})


# ── Scenario evaluation definitions ──────────────────────────────────────────

SCENARIO_SPECS = {
    1: {
        "name":                    "The Missed Medication",
        "patient_id":              "PT001",
        "expected_urgency":        "Urgent",
        "has_allergy_conflict":    False,
        "expected_conflict":       True,
        "key_expected_actions":    ["arb", "ibuprofen", "clinical contact"],
    },
    2: {
        "name":                    "The False Alarm",
        "patient_id":              "PT002",
        "expected_urgency":        "Informational",
        "has_allergy_conflict":    False,
        "expected_conflict":       False,
        "key_expected_actions":    ["no immediate action"],
    },
    3: {
        "name":                    "The Silent Deterioration",
        "patient_id":              "PT003",
        "expected_urgency":        "Critical",
        "has_allergy_conflict":    True,
        "expected_conflict":       False,
        "key_expected_actions":    ["ibuprofen", "clinical assessment", "labs"],
    },
    4: {
        "name":                    "The Incomplete Record",
        "patient_id":              "PT004",
        "expected_urgency":        "Urgent",
        "has_allergy_conflict":    False,
        "expected_conflict":       False,
        "key_expected_actions":    ["pseudoephedrine", "clinical review"],
    },
    5: {
        "name":                    "The Conflicting Data",
        "patient_id":              "PT005",
        "expected_urgency":        "Urgent",
        "has_allergy_conflict":    False,
        "expected_conflict":       True,
        "key_expected_actions":    ["adherence", "alcohol", "do not increase"],
    },
}


# ── Main evaluation runner ─────────────────────────────────────────────────────

def evaluate_scenario(scenario_num: int, ccb: dict, spec: dict) -> dict:
    """Run all checks for one scenario and return results."""
    checks = [
        score_urgency(
            ccb.get("alert_summary", {}).get("urgency_classification", ""),
            spec["expected_urgency"],
        ),
        score_disclaimer_present(ccb),
        score_allergy_flag(ccb, spec["has_allergy_conflict"]),
        score_recommended_actions(ccb, spec["key_expected_actions"]),
        score_conflicts_detected(ccb, spec["expected_conflict"]),
        score_source_citations(ccb),
        score_confidence_in_bounds(ccb),
        score_no_diagnostic_language(ccb),
    ]

    passed      = sum(1 for c in checks if c["pass"])
    total       = len(checks)
    scenario_ok = passed == total

    return {
        "scenario":    scenario_num,
        "name":        spec["name"],
        "patient_id":  spec["patient_id"],
        "pass":        scenario_ok,
        "checks_pass": f"{passed}/{total}",
        "score":       round(passed / total, 2),
        "checks":      checks,
    }


def run_evaluation(use_mock: bool = True) -> dict:
    """Run evaluation across all 5 scenarios."""
    print("\n=== ClinicalBridge Evaluation Harness ===")
    print(f"Mode:  {'Mock outputs (no API calls)' if use_mock else 'Live pipeline'}")
    print(f"Date:  {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 42)

    results       = []
    scenarios_pass = 0

    for num, spec in SCENARIO_SPECS.items():
        print(f"\nScenario {num}: {spec['name']} (Patient {spec['patient_id']})")

        if use_mock:
            ccb = get_mock_ccb(num)
        else:
            # Live mode — import and run the full pipeline
            sys.path.insert(0, str(Path(__file__).parent.parent))
            from agents.orchestrator import run_pipeline
            from main import SCENARIO_ALERTS
            alert = SCENARIO_ALERTS[num]
            print("  Running pipeline...")
            ccb = run_pipeline(alert)

        result = evaluate_scenario(num, ccb, spec)
        results.append(result)

        status = "✅ PASS" if result["pass"] else "❌ FAIL"
        print(f"  {status} | Checks: {result['checks_pass']} | Score: {result['score']}")

        for check in result["checks"]:
            icon = "  ✓" if check["pass"] else "  ✗"
            detail = check.get("detail") or check.get("violations") or ""
            print(f"  {icon} {check['metric']}: {detail}")

        if result["pass"]:
            scenarios_pass += 1

    # ── Summary ──────────────────────────────────────────────────────────────
    total_checks_pass = sum(
        int(r["checks_pass"].split("/")[0]) for r in results
    )
    total_checks = sum(
        int(r["checks_pass"].split("/")[1]) for r in results
    )

    summary = {
        "evaluation_date":    datetime.utcnow().isoformat(),
        "prompt_version":     "v2 (mock) / v3 (live)",
        "mode":               "mock" if use_mock else "live",
        "scenarios_pass":     f"{scenarios_pass}/5",
        "total_checks_pass":  f"{total_checks_pass}/{total_checks}",
        "overall_score":      round(total_checks_pass / total_checks, 2),
        "scenario_results":   results,
    }

    print(f"\n{'='*42}")
    print(f"OVERALL: {scenarios_pass}/5 scenarios passed")
    print(f"CHECKS:  {total_checks_pass}/{total_checks} individual checks passed")
    print(f"SCORE:   {summary['overall_score']}")

    # Save results
    output_path = Path("evaluation/evaluation_run_results.json")
    with open(output_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\nResults saved to {output_path}")

    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    group  = parser.add_mutually_exclusive_group()
    group.add_argument("--mock", action="store_true", default=True,
                       help="Use mock CCB outputs (no API calls)")
    group.add_argument("--live", action="store_true",
                       help="Run full live pipeline (requires OPENAI_API_KEY)")
    args = parser.parse_args()

    use_mock = not args.live
    run_evaluation(use_mock=use_mock)

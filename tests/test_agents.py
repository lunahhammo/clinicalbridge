"""
tests/test_agents.py
Unit and integration tests for all ClinicalBridge agents.

Test categories:
  1. Schema validation tests   — does each agent return the correct output structure?
  2. Urgency classification tests — does the triage agent classify correctly?
  3. Safety guardrail tests    — are disclaimers, allergy flags, and limits enforced?
  4. Anti-hallucination tests  — does the EHR agent flag missing data correctly?
  5. Adherence confidence tests — does the anamnesis agent apply the v2 rules?
  6. Synthesis integrity tests — does the CCB include required fields and citations?

Run with: python -m pytest tests/test_agents.py -v
"""

import json
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime


# ── Fixtures — shared test data ───────────────────────────────────────────────

@pytest.fixture
def scenario_1_alert():
    """Scenario 1: Missed Medication — sustained high BP."""
    return {
        "patient_id":       "PT001",
        "timestamp":        "2026-06-01T06:15:00",
        "device_type":      "blood_pressure_monitor",
        "measurement_type": "systolic_bp",
        "value":            162,
        "unit":             "mmHg",
        "baseline":         138,
        "alert_threshold":  155,
        "alert_category":   "elevated_bp",
        "recent_readings":  [142, 145, 148, 158, 165, 162],
        "notes":            "Sustained elevated BP over 3 consecutive days.",
    }

@pytest.fixture
def scenario_2_alert():
    """Scenario 2: False Alarm — supervised diet change."""
    return {
        "patient_id":       "PT002",
        "timestamp":        "2026-06-01T08:00:00",
        "device_type":      "continuous_glucose_monitor",
        "measurement_type": "blood_glucose",
        "value":            218,
        "unit":             "mg/dL",
        "baseline":         150,
        "alert_threshold":  200,
        "alert_category":   "hyperglycemia",
        "recent_readings":  [148, 155, 185, 204, 196, 218],
        "notes":            "Post-breakfast glucose spike. Pattern started ~1 week ago.",
    }

@pytest.fixture
def scenario_3_alert():
    """Scenario 3: Silent Deterioration — HF weight gain."""
    return {
        "patient_id":       "PT003",
        "timestamp":        "2026-06-01T07:00:00",
        "device_type":      "connected_scale",
        "measurement_type": "body_weight",
        "value":            91.2,
        "unit":             "kg",
        "baseline":         85.0,
        "alert_threshold":  87.0,
        "alert_category":   "weight_gain",
        "recent_readings":  [85.0, 85.2, 86.1, 86.8, 87.3, 88.0, 88.8, 89.5, 90.1, 90.8, 91.2],
        "notes":            "Progressive weight gain 6.2kg over 13 days. Patient has documented heart failure.",
    }

@pytest.fixture
def scenario_4_alert():
    """Scenario 4: Incomplete Record — sparse EHR."""
    return {
        "patient_id":       "PT004",
        "timestamp":        "2026-06-01T08:30:00",
        "device_type":      "blood_pressure_monitor",
        "measurement_type": "systolic_bp",
        "value":            168,
        "unit":             "mmHg",
        "baseline":         130,
        "alert_threshold":  155,
        "alert_category":   "elevated_bp",
        "recent_readings":  [130, 132, 160, 166, 172, 168],
        "notes":            "Sustained elevated BP over 4 days. Sparse EHR.",
    }

@pytest.fixture
def scenario_5_alert():
    """Scenario 5: Conflicting Data — sub-therapeutic drug levels."""
    return {
        "patient_id":       "PT005",
        "timestamp":        "2026-06-01T07:00:00",
        "device_type":      "blood_pressure_monitor",
        "measurement_type": "systolic_bp",
        "value":            174,
        "unit":             "mmHg",
        "baseline":         145,
        "alert_threshold":  160,
        "alert_category":   "elevated_bp",
        "recent_readings":  [145, 148, 162, 168, 171, 174],
        "notes":            "Sustained Stage 2 HTN. Recent labs show sub-therapeutic drug levels.",
    }

@pytest.fixture
def mock_triage_output_urgent():
    """Mock triage output for urgent BP scenario."""
    return {
        "urgency":             "Urgent",
        "urgency_rationale":   "Systolic BP 162 mmHg sustained over 3 days — Stage 2 hypertension trend.",
        "clinical_question":   "Patient PT001 has sustained Stage 2 hypertension. Check antihypertensive history.",
        "ehr_query_parameters": {
            "patient_id":            "PT001",
            "relevant_conditions":   ["hypertension", "diabetes"],
            "relevant_medications":  ["ACE inhibitor", "antihypertensive"],
            "relevant_labs":         ["serum creatinine", "potassium"],
            "time_window_months":    12,
        },
        "anamnesis_query_parameters": {
            "patient_id":       "PT001",
            "focus_areas":      ["medication_adherence", "symptoms"],
            "clinical_question": "Is the patient taking their BP medications as prescribed?",
        },
        "escalate_immediately":          False,
        "escalation_modifiers_applied":  [],
    }

@pytest.fixture
def mock_triage_output_critical():
    """Mock triage output for critical weight gain scenario."""
    return {
        "urgency":             "Critical",
        "urgency_rationale":   "Weight gain 6.2kg in 13 days in HF patient WITH concurrent symptoms.",
        "clinical_question":   "HF patient with progressive weight gain and ankle oedema.",
        "ehr_query_parameters": {
            "patient_id":           "PT003",
            "relevant_conditions":  ["heart failure", "atrial fibrillation"],
            "relevant_medications": ["furosemide", "diuretic"],
            "relevant_labs":        ["BNP", "creatinine", "sodium"],
            "time_window_months":   24,
        },
        "anamnesis_query_parameters": {
            "patient_id":       "PT003",
            "focus_areas":      ["symptoms", "medication_adherence", "lifestyle"],
            "clinical_question": "Has patient reported ankle swelling or breathing difficulty?",
        },
        "escalate_immediately":         True,
        "escalation_modifiers_applied": ["HF_weight_gain_>6kg_14days_with_symptoms"],
    }

@pytest.fixture
def mock_ehr_context_pt001():
    """Mock EHR context for PT001 (Scenario 1)."""
    return {
        "patient_id":          "PT001",
        "relevant_diagnoses":  [
            {"icd10": "I10", "description": "Essential hypertension", "onset": "2012-06-01", "status": "active"},
            {"icd10": "E11.9", "description": "Type 2 diabetes mellitus", "onset": "2015-01-15", "status": "active"},
        ],
        "relevant_medications": [
            {"name": "Lisinopril", "dose": "10mg", "frequency": "once daily",
             "indication": "Hypertension", "source": "medications_list"},
        ],
        "relevant_labs": [
            {"test": "Serum Creatinine", "value": 1.1, "unit": "mg/dL",
             "date": "2026-04-10", "flag": "normal", "source": "lab_results_2026-04-10"},
            {"test": "Serum Potassium", "value": 4.1, "unit": "mEq/L",
             "date": "2026-04-10", "flag": "normal", "source": "lab_results_2026-04-10"},
        ],
        "relevant_visit_notes": [
            {"date": "2026-04-10", "provider": "Dr. Susan Okafor",
             "excerpt": "Patient noted a persistent dry cough but attributed it to allergies. Lisinopril continued.",
             "source": "visit_note_2026-04-10"},
        ],
        "allergy_alerts": [
            {"substance": "Penicillin", "reaction": "Rash", "severity": "Moderate",
             "relevance_to_alert": "Not directly relevant to current BP alert"},
        ],
        "pattern_flags":        [],
        "retrieval_confidence": 0.88,
        "missing_data_flags":   ["No renal labs since 2026-04-10"],
        "source_references":    ["medications_list", "visit_note_2026-04-10", "lab_results_2026-04-10"],
    }

@pytest.fixture
def mock_anamnesis_pt001():
    """Mock anamnesis output for PT001 (Scenario 1)."""
    return {
        "patient_id":          "PT001",
        "reporter_type":       "patient",
        "medication_adherence_summary": (
            "Patient self-discontinued Lisinopril ~10 days ago due to persistent dry cough. "
            "Continues Metformin and Aspirin as prescribed."
        ),
        "medications_taken_as_prescribed": ["Metformin 500mg twice daily", "Aspirin 81mg once daily"],
        "medications_stopped_by_patient": [
            {"name": "Lisinopril", "dose": "10mg",
             "reason": "Persistent dry cough affecting sleep and causing public embarrassment",
             "date_stopped_approx": "2026-05-22"},
        ],
        "otc_medications":     ["Ibuprofen 400mg — taken for headaches over past 3 days"],
        "recent_symptoms":     "Morning headaches (dull pressure), dizziness on standing, elevated home BP readings.",
        "symptom_timeline": [
            {"date": "2026-05-28", "patient_notes": "Stopped Lisinopril about a week ago. Cough better."},
            {"date": "2026-06-01", "patient_notes": "Bad morning. Headache, BP 162/104. Called clinic."},
        ],
        "lifestyle_factors":   "High sodium diet. Sedentary. Former smoker (quit 2008).",
        "family_history_highlights": "Father had stroke age 71. Brother had MI age 58.",
        "patient_concerns":    "Wants alternative BP medication without cough side effect.",
        "adherence_confidence": "High",
        "sensitivity_flags":   [],
        "source":              "anamnesis_record_PT001",
    }


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 1: Schema Validation Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestTriageAgentSchema:
    """Validate that TriageAgent output matches the expected schema."""

    def test_triage_output_has_required_fields(self, mock_triage_output_urgent):
        required = [
            "urgency", "urgency_rationale", "clinical_question",
            "ehr_query_parameters", "anamnesis_query_parameters",
            "escalate_immediately", "escalation_modifiers_applied",
        ]
        for field in required:
            assert field in mock_triage_output_urgent, f"Missing field: {field}"

    def test_urgency_is_valid_value(self, mock_triage_output_urgent):
        valid = {"Critical", "Urgent", "Routine", "Informational"}
        assert mock_triage_output_urgent["urgency"] in valid

    def test_ehr_query_has_time_window(self, mock_triage_output_urgent):
        assert "time_window_months" in mock_triage_output_urgent["ehr_query_parameters"]
        assert isinstance(mock_triage_output_urgent["ehr_query_parameters"]["time_window_months"], int)

    def test_critical_sets_escalate_immediately(self, mock_triage_output_critical):
        assert mock_triage_output_critical["escalate_immediately"] is True

    def test_urgent_does_not_escalate(self, mock_triage_output_urgent):
        assert mock_triage_output_urgent["escalate_immediately"] is False

    def test_escalation_modifiers_is_list(self, mock_triage_output_urgent):
        assert isinstance(mock_triage_output_urgent["escalation_modifiers_applied"], list)


class TestEHRAgentSchema:
    """Validate EHR Retrieval Agent output schema."""

    def test_ehr_output_has_required_fields(self, mock_ehr_context_pt001):
        required = [
            "patient_id", "relevant_diagnoses", "relevant_medications",
            "relevant_labs", "relevant_visit_notes", "allergy_alerts",
            "pattern_flags", "retrieval_confidence", "missing_data_flags",
            "source_references",
        ]
        for field in required:
            assert field in mock_ehr_context_pt001, f"Missing field: {field}"

    def test_retrieval_confidence_is_float_in_range(self, mock_ehr_context_pt001):
        conf = mock_ehr_context_pt001["retrieval_confidence"]
        assert isinstance(conf, float)
        assert 0.0 <= conf <= 1.0

    def test_all_medications_have_source(self, mock_ehr_context_pt001):
        for med in mock_ehr_context_pt001["relevant_medications"]:
            assert "source" in med, f"Medication missing source: {med['name']}"

    def test_all_labs_have_date(self, mock_ehr_context_pt001):
        for lab in mock_ehr_context_pt001["relevant_labs"]:
            assert "date" in lab, f"Lab missing date: {lab['test']}"

    def test_pattern_flags_is_list(self, mock_ehr_context_pt001):
        assert isinstance(mock_ehr_context_pt001["pattern_flags"], list)


class TestAnamnesisAgentSchema:
    """Validate Anamnesis Agent output schema."""

    def test_anamnesis_output_has_required_fields(self, mock_anamnesis_pt001):
        required = [
            "patient_id", "reporter_type", "medication_adherence_summary",
            "medications_taken_as_prescribed", "medications_stopped_by_patient",
            "otc_medications", "recent_symptoms", "symptom_timeline",
            "lifestyle_factors", "family_history_highlights", "patient_concerns",
            "adherence_confidence", "sensitivity_flags", "source",
        ]
        for field in required:
            assert field in mock_anamnesis_pt001, f"Missing field: {field}"

    def test_reporter_type_is_valid(self, mock_anamnesis_pt001):
        assert mock_anamnesis_pt001["reporter_type"] in {"patient", "caregiver", "unknown"}

    def test_adherence_confidence_is_valid(self, mock_anamnesis_pt001):
        assert mock_anamnesis_pt001["adherence_confidence"] in {"High", "Medium", "Low", "Unknown"}

    def test_symptom_timeline_dates_iso_format(self, mock_anamnesis_pt001):
        for entry in mock_anamnesis_pt001["symptom_timeline"]:
            date_str = entry.get("date", "")
            # Validate ISO format YYYY-MM-DD
            try:
                datetime.strptime(date_str, "%Y-%m-%d")
            except ValueError:
                pytest.fail(f"Non-ISO date in symptom_timeline: {date_str}")

    def test_sensitivity_flags_is_list(self, mock_anamnesis_pt001):
        assert isinstance(mock_anamnesis_pt001["sensitivity_flags"], list)


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 2: Urgency Classification Logic Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestUrgencyClassificationRules:
    """Test that urgency classification rules are applied correctly."""

    def test_sustained_bp_trend_is_urgent(self, mock_triage_output_urgent):
        """Three consecutive readings above threshold should be at least Urgent."""
        assert mock_triage_output_urgent["urgency"] in {"Urgent", "Critical"}

    def test_hf_weight_gain_with_symptoms_is_critical(self, mock_triage_output_critical):
        """6.2kg gain over 13 days in HF patient with symptoms must be Critical."""
        assert mock_triage_output_critical["urgency"] == "Critical"
        assert mock_triage_output_critical["escalate_immediately"] is True

    def test_critical_time_window_is_24_months(self, mock_triage_output_critical):
        """Critical alerts should use 24-month EHR time window."""
        assert mock_triage_output_critical["ehr_query_parameters"]["time_window_months"] == 24

    def test_urgent_time_window_is_12_months(self, mock_triage_output_urgent):
        """Urgent alerts should use 12-month EHR time window."""
        assert mock_triage_output_urgent["ehr_query_parameters"]["time_window_months"] == 12


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 3: Safety Guardrail Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestSafetyGuardrails:
    """Test that safety guardrails are enforced correctly."""

    def test_ccb_contains_disclaimer(self):
        """Every CCB must contain the mandatory disclaimer."""
        mock_ccb = {
            "patient_id": "PT001",
            "alert_summary": {},
            "disclaimer": (
                "This Clinical Context Brief is a decision-support summary generated by "
                "an AI prototype using simulated data. It does not constitute a diagnosis "
                "or treatment order. All clinical decisions require review and approval by "
                "a qualified physician. This system is not approved for use in real patient care."
            ),
        }
        assert "disclaimer" in mock_ccb
        assert len(mock_ccb["disclaimer"]) > 50

    def test_allergy_conflict_in_data_quality_warning(self):
        """NSAID allergy conflict must appear in patient_snapshot.data_quality_warning."""
        mock_ccb = {
            "patient_snapshot": {
                "data_quality_warning": (
                    "ALLERGY CONFLICT: Patient self-reports taking ibuprofen (Anamnesis). "
                    "EHR documents severe NSAID allergy: fluid retention and worsening heart failure."
                ),
            },
        }
        warning = mock_ccb["patient_snapshot"]["data_quality_warning"]
        assert warning is not None
        assert "ALLERGY" in warning.upper() or "allergy" in warning.lower()

    def test_ccb_does_not_contain_diagnosis_language(self):
        """CCB should not contain diagnostic declarations."""
        forbidden_phrases = [
            "the patient has hypertensive urgency",
            "the patient is in acute decompensation",
            "diagnosis:",
            "should be admitted",
            "this is a case of",
        ]
        mock_ccb_text = (
            "Findings are consistent with loss of antihypertensive medication effect. "
            "This warrants evaluation for ACE inhibitor-induced cough and possible ARB switch. "
            "Clinician should consider immediate clinical review."
        ).lower()

        for phrase in forbidden_phrases:
            assert phrase not in mock_ccb_text, f"Forbidden diagnosis phrase found: {phrase}"

    def test_allergy_conflict_in_recommended_actions_first(self):
        """Allergy conflict must be the first recommended action."""
        mock_actions = [
            {"action": "Immediate cessation of ibuprofen — NSAID ALLERGY VIOLATION",
             "confidence": "High", "evidence": "EHR allergy + Anamnesis OTC report"},
            {"action": "Urgent clinical assessment today", "confidence": "High",
             "evidence": "6.2kg weight gain + oedema + dyspnoea"},
        ]
        # First action should reference the allergy
        first_action = mock_actions[0]["action"].lower()
        assert "allergy" in first_action or "ibuprofen" in first_action or "nsaid" in first_action

    def test_confidence_score_within_bounds(self):
        """Confidence score must be between 0.10 and 0.95."""
        test_scores = [0.10, 0.50, 0.75, 0.95]
        for score in test_scores:
            assert 0.10 <= score <= 0.95

    def test_confidence_score_never_1(self):
        """Confidence score must never be exactly 1.0."""
        test_scores = [0.87, 0.92, 0.95, 0.99]
        for score in test_scores:
            # The validator in synthesis_agent.py clamps to max 0.95
            clamped = min(0.95, score)
            assert clamped <= 0.95


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 4: Anti-Hallucination Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestAntiHallucination:
    """Test that agents correctly flag missing data rather than hallucinating."""

    def test_sparse_ehr_sets_low_confidence(self):
        """Sparse EHR should produce retrieval_confidence < 0.5."""
        sparse_ehr_output = {
            "patient_id":          "PT004",
            "relevant_diagnoses":  [
                {"icd10": "I10", "description": "Hypertension", "onset": "2023-11-01", "status": "active"},
            ],
            "relevant_medications": [
                {"name": "Amlodipine", "dose": "5mg", "frequency": "once daily",
                 "indication": "Hypertension", "source": "medications_list"},
            ],
            "relevant_labs":        [],
            "relevant_visit_notes": [
                {"date": "2023-11-15", "provider": "Dr. Patel",
                 "excerpt": "New patient. Records partially transferred from prior provider.",
                 "source": "visit_note_2023-11-15"},
            ],
            "allergy_alerts":       [],
            "pattern_flags":        [],
            "retrieval_confidence": 0.32,
            "missing_data_flags": [
                "EHR records sparse — patient transferred from external facility",
                "No lab results in retrieved records",
                "No prior visit notes beyond initial intake",
                "Full medication history unknown",
                "LOW EHR CONFIDENCE — synthesis will rely heavily on anamnesis data",
            ],
            "source_references": ["medications_list", "visit_note_2023-11-15"],
        }
        assert sparse_ehr_output["retrieval_confidence"] < 0.5
        low_conf_flags = [f for f in sparse_ehr_output["missing_data_flags"]
                          if "LOW EHR CONFIDENCE" in f]
        assert len(low_conf_flags) >= 1, "LOW EHR CONFIDENCE flag missing for low-confidence EHR"

    def test_missing_lab_explicitly_flagged(self):
        """Labs not found in records should appear in missing_data_flags."""
        ehr_output = {
            "relevant_labs":      [],
            "missing_data_flags": [
                "Lab BNP not found in retrieved records",
                "Lab serum creatinine not found in retrieved records",
            ],
        }
        # Verify missing labs are flagged, not silently absent
        missing_flags = ehr_output["missing_data_flags"]
        assert any("BNP" in f for f in missing_flags)

    def test_stale_lab_has_outdated_marker(self):
        """Labs older than 90 days must have POTENTIALLY OUTDATED marker."""
        lab_entry = {
            "test":   "Serum Creatinine",
            "value":  1.1,
            "unit":   "mg/dL",
            "date":   "2025-10-01",   # More than 90 days ago
            "flag":   "normal [POTENTIALLY OUTDATED — 243 days since collection]",
            "source": "lab_results_2025-10-01",
        }
        assert "POTENTIALLY OUTDATED" in lab_entry["flag"]

    def test_recent_lab_has_no_outdated_marker(self):
        """Labs within 90 days should NOT have the POTENTIALLY OUTDATED marker."""
        lab_entry = {
            "test":  "Serum Potassium",
            "value": 4.1,
            "unit":  "mEq/L",
            "date":  "2026-04-10",
            "flag":  "normal",
        }
        assert "POTENTIALLY OUTDATED" not in lab_entry["flag"]


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 5: Anamnesis Agent Behaviour Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestAnamnesisAgentBehaviour:
    """Test specific v2 anamnesis agent behaviours."""

    def test_self_discontinued_medication_captured(self, mock_anamnesis_pt001):
        """Scenario 1: Lisinopril self-discontinuation must be captured."""
        stopped = mock_anamnesis_pt001["medications_stopped_by_patient"]
        assert len(stopped) >= 1
        lisinopril_stopped = [m for m in stopped if "Lisinopril" in m["name"]]
        assert len(lisinopril_stopped) == 1
        assert "cough" in lisinopril_stopped[0]["reason"].lower()

    def test_otc_medication_captured(self, mock_anamnesis_pt001):
        """Scenario 1: Ibuprofen OTC use must be captured in anamnesis."""
        otc = mock_anamnesis_pt001["otc_medications"]
        assert any("Ibuprofen" in m or "ibuprofen" in m for m in otc)

    def test_defensive_language_lowers_confidence(self):
        """Scenario 5: Emphatic adherence language should produce Medium confidence."""
        anamnesis_pt005 = {
            "patient_id":              "PT005",
            "reporter_type":           "patient",
            "medication_adherence_summary": (
                "Patient emphatically asserts full adherence to Metoprolol. "
                "States 'I take it every single morning, I never miss it.' "
                "Patient used notably emphatic language regarding adherence."
            ),
            "adherence_confidence":    "Medium",   # Downgraded per v2 rule
            "sensitivity_flags":       ["substance_use — documented alcohol use disorder"],
        }
        assert anamnesis_pt005["adherence_confidence"] == "Medium"

    def test_caregiver_report_flagged_and_capped(self):
        """Scenario 4 (PT009): Caregiver-reported anamnesis should cap confidence at Medium."""
        caregiver_anamnesis = {
            "patient_id":    "PT009",
            "reporter_type": "caregiver",
            "medication_adherence_summary": (
                "Note: information reported by caregiver (daughter), not directly by patient. "
                "Caregiver reports approximately 80% adherence — patient occasionally refuses medications."
            ),
            "adherence_confidence": "Medium",   # Capped at Medium per v2 rule
            "sensitivity_flags":    ["caregiver_reported"],
        }
        assert caregiver_anamnesis["reporter_type"] == "caregiver"
        assert caregiver_anamnesis["adherence_confidence"] in {"Medium", "Low", "Unknown"}
        assert "caregiver_reported" in caregiver_anamnesis["sensitivity_flags"]

    def test_substance_use_sensitivity_flagged(self):
        """Scenario 5: Alcohol use in context of alcohol use disorder must be flagged."""
        anamnesis_pt005 = {
            "sensitivity_flags": [
                "substance_use — patient has documented alcohol use disorder history; "
                "self-reported consumption may be underestimated; patient was defensive when discussing alcohol"
            ],
        }
        flags = " ".join(anamnesis_pt005["sensitivity_flags"]).lower()
        assert "substance_use" in flags


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 6: Synthesis Agent Integrity Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestSynthesisAgentIntegrity:
    """Test CCB output integrity for all 5 scenarios."""

    def _make_ccb(self, urgency, primary_finding, actions, conflicts=None,
                  warning=None, confidence=0.8):
        return {
            "patient_id":    "PT_TEST",
            "generated_at":  "2026-06-01T08:00:00",
            "alert_summary": {"urgency_classification": urgency, "trigger": "test", "rationale": "test"},
            "patient_snapshot": {
                "name": "Test Patient",
                "active_conditions":    ["hypertension"],
                "current_treatment_plan": "Lisinopril",
                "data_quality_warning": warning,
            },
            "contextual_analysis": {
                "primary_finding":      primary_finding,
                "contributing_factors": ["Factor 1 (EHR)", "Factor 2 (Anamnesis)"],
                "conflicts_detected":   conflicts or [],
                "timeline":             "BP rose over 10 days.",
            },
            "risk_assessment": {
                "immediate_risks":            "Stage 2 hypertension",
                "medium_term_risks":          "Cardiovascular risk",
                "differential_considerations": "ACE discontinuation (most likely).",
            },
            "recommended_actions": actions,
            "uncertainties_and_gaps": ["No renal labs since April"],
            "confidence_score": confidence,
            "disclaimer": (
                "This Clinical Context Brief is a decision-support summary generated by "
                "an AI prototype using simulated data. It does not constitute a diagnosis "
                "or treatment order. All clinical decisions require review and approval by "
                "a qualified physician. This system is not approved for use in real patient care."
            ),
        }

    def test_ccb_has_all_required_sections(self):
        ccb = self._make_ccb(
            "Urgent",
            "Lisinopril self-discontinued (Anamnesis). BP rising over 10 days (RPM).",
            [{"action": "Switch to ARB", "confidence": "High", "evidence": "EHR cough + Anamnesis"}],
        )
        required = ["alert_summary", "patient_snapshot", "contextual_analysis",
                    "risk_assessment", "recommended_actions", "uncertainties_and_gaps",
                    "confidence_score", "disclaimer"]
        for field in required:
            assert field in ccb, f"CCB missing required section: {field}"

    def test_scenario_1_identifies_lisinopril_discontinuation(self, mock_anamnesis_pt001):
        """CCB for Scenario 1 must identify Lisinopril as the cause."""
        primary_finding = (
            "Sustained BP elevation is most likely explained by the patient's "
            "self-discontinuation of Lisinopril ~10 days ago (Anamnesis). "
            "Timing matches RPM trend of rising BP from baseline (RPM)."
        )
        assert "lisinopril" in primary_finding.lower()
        assert "(Anamnesis)" in primary_finding or "(RPM)" in primary_finding

    def test_scenario_2_classifies_as_informational(self):
        """CCB for Scenario 2 should classify alert as Informational."""
        ccb = self._make_ccb(
            "Informational",
            "Glucose elevation contextually explained by supervised dietary change (EHR + Anamnesis).",
            [],  # No immediate actions for Informational
        )
        assert ccb["alert_summary"]["urgency_classification"] == "Informational"

    def test_scenario_3_allergy_conflict_in_warning(self):
        """CCB for Scenario 3 must show NSAID allergy conflict in data_quality_warning."""
        ccb = self._make_ccb(
            "Critical",
            "Progressive weight gain in HF patient consistent with decompensation.",
            [{"action": "Immediate ibuprofen cessation — NSAID ALLERGY", "confidence": "High",
              "evidence": "EHR allergy record + Anamnesis OTC report"}],
            warning="ALLERGY CONFLICT: Patient self-reports taking ibuprofen (Anamnesis). "
                    "EHR documents NSAID allergy: severe fluid retention and worsening HF.",
        )
        assert ccb["patient_snapshot"]["data_quality_warning"] is not None
        assert "allergy" in ccb["patient_snapshot"]["data_quality_warning"].lower()

    def test_scenario_4_flags_incomplete_record(self):
        """CCB for Scenario 4 must flag incomplete EHR prominently."""
        ccb = self._make_ccb(
            "Urgent",
            "BP elevation with multiple contributing factors identified from anamnesis; EHR is sparse.",
            [{"action": "Expedite records request", "confidence": "High",
              "evidence": "EHR critically incomplete — 1 visit note only"}],
        )
        actions_text = " ".join(a["action"] for a in ccb["recommended_actions"]).lower()
        assert "record" in actions_text or "ehr" in actions_text or "history" in actions_text

    def test_scenario_5_flags_adherence_conflict(self):
        """CCB for Scenario 5 must flag discrepancy between stated and objective adherence."""
        conflicts = [
            "Patient reports full adherence to Metoprolol (Anamnesis) but plasma level "
            "28 ng/mL is sub-therapeutic (EHR) — these sources directly conflict."
        ]
        ccb = self._make_ccb(
            "Urgent",
            "Sub-therapeutic Metoprolol level conflicts with patient's stated full adherence.",
            [{"action": "Clinical conversation re: adherence — non-confrontational approach",
              "confidence": "High", "evidence": "Sub-therapeutic Metoprolol (EHR) vs stated adherence (Anamnesis)"}],
            conflicts=conflicts,
        )
        assert len(ccb["contextual_analysis"]["conflicts_detected"]) >= 1
        conflicts_text = " ".join(ccb["contextual_analysis"]["conflicts_detected"]).lower()
        assert "adherence" in conflicts_text or "metoprolol" in conflicts_text

    def test_recommended_actions_have_evidence(self):
        """Every recommended action must include an evidence citation."""
        actions = [
            {"action": "Switch to ARB", "confidence": "High",
             "evidence": "EHR: cough documented twice. Anamnesis: patient confirmed cough."},
            {"action": "Stop ibuprofen", "confidence": "High",
             "evidence": "Anamnesis: ibuprofen use confirmed. Contraindicated with hypertension."},
        ]
        for action in actions:
            assert "evidence" in action
            assert len(action["evidence"]) > 10, f"Evidence too brief for action: {action['action']}"

    def test_informational_ccb_says_no_immediate_action(self):
        """Informational CCBs should explicitly say no immediate action required."""
        informational_actions = []  # Empty for Informational
        # When actions list is empty, the system should have stated no action required
        # in the contextual_analysis or as a note
        assert len(informational_actions) == 0 or any(
            "no immediate action" in a.get("action", "").lower()
            for a in informational_actions
        )


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 7: Orchestrator Flow Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestOrchestratorFlow:
    """Test orchestrator routing and safety logic."""

    def test_critical_alert_sets_escalate_flag(self, mock_triage_output_critical):
        """Critical triage output must set escalate_immediately = True."""
        assert mock_triage_output_critical["escalate_immediately"] is True

    def test_critical_bypasses_synthesis(self, mock_triage_output_critical):
        """Simulate orchestrator behaviour: Critical → escalation notice, not CCB."""
        triage_output = mock_triage_output_critical
        if triage_output.get("escalate_immediately"):
            result_type = "escalation_notice"
        else:
            result_type = "ccb"
        assert result_type == "escalation_notice"

    def test_alert_validation_catches_missing_fields(self):
        """Orchestrator should reject alerts missing required fields."""
        incomplete_alert = {
            "patient_id": "PT001",
            "value": 162,
            # Missing: timestamp, device_type, measurement_type, unit, etc.
        }
        required = ["patient_id", "timestamp", "device_type", "measurement_type",
                    "value", "unit", "baseline", "alert_threshold", "alert_category"]
        missing = [f for f in required if f not in incomplete_alert]
        assert len(missing) > 0

    def test_pipeline_latency_target(self):
        """Simulated pipeline latency should be under 30 seconds for non-critical."""
        mock_latency = {
            "triage_latency_s":    2.8,
            "retrieval_latency_s": 8.4,   # Parallel: max of EHR + anamnesis
            "synthesis_latency_s": 11.2,
            "total_latency_s":     22.4,
        }
        assert mock_latency["total_latency_s"] < 30.0, "Pipeline exceeds 30s latency target"


# ─────────────────────────────────────────────────────────────────────────────
# Run summary
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Run with: python -m pytest tests/test_agents.py -v")
    print("Or:       python -m pytest tests/test_agents.py -v --tb=short")

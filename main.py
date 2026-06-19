"""
main.py
ClinicalBridge — Entry Point

Usage:
    python main.py --scenario 1        # Run a preset scenario (1-5)
    python main.py --patient PT001     # Run the current alert for a specific patient
    python main.py --alert alert.json  # Run from a custom alert JSON file

Scenarios:
    1 = The Missed Medication  (PT001 — Mehmet Yıldız)
    2 = The False Alarm        (PT002 — Ayşe Kaya)
    3 = The Silent Deterioration (PT003 — Hasan Demir)
    4 = The Incomplete Record  (PT004 — Elif Şahin)
    5 = The Conflicting Data   (PT005 — Kemal Aydın)
"""

import argparse
import json
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Check API key before importing agents
if not os.getenv("OPENAI_API_KEY"):
    print("ERROR: OPENAI_API_KEY not found.")
    print("Create a .env file with: OPENAI_API_KEY=your_key_here")
    sys.exit(1)

from agents.orchestrator import run_pipeline


# ── Preset scenario alerts ────────────────────────────────────────────────────
# These are the triggering RPM alerts for each of the 5 clinical scenarios.
# In a real system these would arrive from the RPM device stream.

SCENARIO_ALERTS = {
    1: {
        "patient_id":      "PT001",
        "timestamp":       "2026-06-01T06:15:00",
        "device_type":     "blood_pressure_monitor",
        "measurement_type": "systolic_bp",
        "value":           162,
        "unit":            "mmHg",
        "baseline":        138,
        "alert_threshold": 155,
        "alert_category":  "elevated_bp",
        "recent_readings": [142, 145, 148, 158, 165, 162],
        "notes":           "Sustained elevated BP over 3 consecutive days. Diastolic also elevated: 104 mmHg (threshold 100 mmHg).",
    },
    2: {
        "patient_id":      "PT002",
        "timestamp":       "2026-06-01T08:00:00",
        "device_type":     "continuous_glucose_monitor",
        "measurement_type": "blood_glucose",
        "value":           218,
        "unit":            "mg/dL",
        "baseline":        150,
        "alert_threshold": 200,
        "alert_category":  "hyperglycemia",
        "recent_readings": [148, 155, 185, 204, 196, 218],
        "notes":           "Post-breakfast glucose spike. Pattern shows elevation starting approximately 1 week ago.",
    },
    3: {
        "patient_id":      "PT003",
        "timestamp":       "2026-06-01T07:00:00",
        "device_type":     "connected_scale",
        "measurement_type": "body_weight",
        "value":           91.2,
        "unit":            "kg",
        "baseline":        85.0,
        "alert_threshold": 87.0,
        "alert_category":  "weight_gain",
        "recent_readings": [85.0, 85.2, 86.1, 86.8, 87.3, 88.0, 88.8, 89.5, 90.1, 90.8, 91.2],
        "notes":           "Progressive weight gain 6.2kg over 13 days. No plateau. Patient has documented heart failure.",
    },
    4: {
        "patient_id":      "PT004",
        "timestamp":       "2026-06-01T08:30:00",
        "device_type":     "blood_pressure_monitor",
        "measurement_type": "systolic_bp",
        "value":           168,
        "unit":            "mmHg",
        "baseline":        130,
        "alert_threshold": 155,
        "alert_category":  "elevated_bp",
        "recent_readings": [130, 132, 160, 166, 172, 168],
        "notes":           "Sustained elevated BP over 4 days. Patient has sparse EHR — transferred from external facility.",
    },
    5: {
        "patient_id":      "PT005",
        "timestamp":       "2026-06-01T07:00:00",
        "device_type":     "blood_pressure_monitor",
        "measurement_type": "systolic_bp",
        "value":           174,
        "unit":            "mmHg",
        "baseline":        145,
        "alert_threshold": 160,
        "alert_category":  "elevated_bp",
        "recent_readings": [145, 148, 162, 168, 171, 174],
        "notes":           "Sustained Stage 2 hypertension despite claimed medication adherence. Recent labs show sub-therapeutic drug levels.",
    },
}


# ── Output formatting ─────────────────────────────────────────────────────────

def print_ccb(ccb: dict) -> None:
    """Pretty-print the Clinical Context Brief to the console."""
    print("\n" + "=" * 70)
    print("  CLINICAL CONTEXT BRIEF — ClinicalBridge")
    print("=" * 70)

    if ccb.get("escalation_type") == "CRITICAL_ALERT":
        print("⚠️  CRITICAL ESCALATION — IMMEDIATE HUMAN REVIEW REQUIRED")
        print(f"   {ccb.get('message')}")
        print(f"   Immediate action: {ccb.get('immediate_action')}")
        print(f"\nTriage urgency rationale:")
        print(f"   {ccb.get('triage_output', {}).get('urgency_rationale', 'N/A')}")
        print("\n" + "=" * 70)
        return

    summary = ccb.get("alert_summary", {})
    print(f"\nPatient:   {ccb.get('patient_snapshot', {}).get('name', 'Unknown')}")
    print(f"Patient ID: {ccb.get('patient_id', 'Unknown')}")
    print(f"Generated: {ccb.get('generated_at', 'Unknown')}")
    print(f"Urgency:   {summary.get('urgency_classification', 'Unknown')}")
    print(f"Confidence: {ccb.get('confidence_score', 'N/A')}")

    warning = ccb.get("patient_snapshot", {}).get("data_quality_warning")
    if warning:
        print(f"\n⚠️  DATA QUALITY WARNING: {warning}")

    print(f"\n--- ALERT SUMMARY ---")
    print(f"Trigger: {summary.get('trigger')}")
    print(f"Rationale: {summary.get('rationale')}")

    analysis = ccb.get("contextual_analysis", {})
    print(f"\n--- CONTEXTUAL ANALYSIS ---")
    print(f"Primary finding: {analysis.get('primary_finding')}")

    factors = analysis.get("contributing_factors", [])
    if factors:
        print("\nContributing factors:")
        for f in factors:
            print(f"  • {f}")

    conflicts = analysis.get("conflicts_detected", [])
    if conflicts:
        print("\nConflicts detected:")
        for c in conflicts:
            print(f"  ⚡ {c}")

    risk = ccb.get("risk_assessment", {})
    print(f"\n--- RISK ASSESSMENT ---")
    print(f"Immediate risks: {risk.get('immediate_risks')}")
    print(f"Medium-term: {risk.get('medium_term_risks')}")

    actions = ccb.get("recommended_actions", [])
    if actions:
        print(f"\n--- RECOMMENDED ACTIONS (ordered by urgency) ---")
        for i, action in enumerate(actions, 1):
            print(f"  {i}. [{action.get('confidence', '?')} confidence] {action.get('action')}")
            print(f"     Evidence: {action.get('evidence')}")

    gaps = ccb.get("uncertainties_and_gaps", [])
    if gaps:
        print(f"\n--- UNCERTAINTIES & GAPS ---")
        for g in gaps:
            print(f"  • {g}")

    meta = ccb.get("_pipeline_meta", {})
    if meta:
        print(f"\n--- PIPELINE METRICS ---")
        print(f"Total latency: {meta.get('total_latency_s')}s")

    print(f"\n--- DISCLAIMER ---")
    print(ccb.get("disclaimer", ""))
    print("\n" + "=" * 70)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="ClinicalBridge — Multi-Agent Clinical Decision Support")
    group  = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--scenario", type=int, choices=[1, 2, 3, 4, 5],
                       help="Run a preset clinical scenario (1-5)")
    group.add_argument("--alert",    type=str,
                       help="Path to a custom RPM alert JSON file")
    parser.add_argument("--output",  type=str, default=None,
                        help="Save CCB output to a JSON file")

    args = parser.parse_args()

    # Load alert
    if args.scenario:
        alert       = SCENARIO_ALERTS[args.scenario]
        scenario_names = {
            1: "The Missed Medication",
            2: "The False Alarm",
            3: "The Silent Deterioration",
            4: "The Incomplete Record",
            5: "The Conflicting Data",
        }
        print(f"\nClinicalBridge — Scenario {args.scenario}: {scenario_names[args.scenario]}")
        print(f"Patient: {alert['patient_id']} | Alert: {alert['measurement_type']} = {alert['value']} {alert['unit']}")
        print("-" * 60)
    else:
        alert_path = Path(args.alert)
        if not alert_path.exists():
            print(f"ERROR: Alert file not found: {args.alert}")
            sys.exit(1)
        with open(alert_path) as f:
            alert = json.load(f)
        print(f"\nClinicalBridge — Custom alert from {args.alert}")

    # Check vector store exists
    if not Path("data/chroma_db").exists():
        print("\nERROR: Vector store not found.")
        print("Please run first: python setup_vectorstore.py")
        sys.exit(1)

    # Run pipeline
    print("\nStarting ClinicalBridge pipeline...\n")
    ccb = run_pipeline(alert)

    # Display results
    print_ccb(ccb)

    # Save output if requested
    if args.output:
        output_path = Path(args.output)
        with open(output_path, "w") as f:
            json.dump(ccb, f, indent=2)
        print(f"\nCCB saved to: {output_path}")

    return ccb


if __name__ == "__main__":
    main()

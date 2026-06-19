"""
agents/triage_agent.py
Alert Triage Agent — classifies RPM alert urgency and formulates retrieval queries.
Uses GPT-4o with JSON mode, temperature=0.0 for deterministic classification.
Implements v2 system prompt from prompts/v2/all_agents_v2.md
"""

import json
from datetime import datetime
from langchain_openai import ChatOpenAI
from langchain.schema import SystemMessage, HumanMessage
from pydantic import BaseModel


# ── Output schema (Pydantic for validation) ──────────────────────────────────

class EHRQueryParams(BaseModel):
    patient_id: str
    relevant_conditions: list[str]
    relevant_medications: list[str]
    relevant_labs: list[str]
    time_window_months: int

class AnamnesisQueryParams(BaseModel):
    patient_id: str
    focus_areas: list[str]
    clinical_question: str

class TriageOutput(BaseModel):
    urgency: str                         # Critical | Urgent | Routine | Informational
    urgency_rationale: str
    clinical_question: str
    ehr_query_parameters: EHRQueryParams
    anamnesis_query_parameters: AnamnesisQueryParams
    escalate_immediately: bool
    escalation_modifiers_applied: list[str]


# ── System prompt (v2) ───────────────────────────────────────────────────────

TRIAGE_SYSTEM_PROMPT = """You are a clinical alert triage specialist. Your role is to receive Remote Patient Monitoring (RPM) alerts and classify their urgency so that downstream agents retrieve the right information.

You are NOT a diagnostician. You do not make diagnoses. You classify urgency and formulate retrieval queries.

URGENCY LEVELS (choose exactly one):
- CRITICAL: Values that may indicate an immediately life-threatening condition. Examples: systolic BP >180, diastolic >120, SpO2 <90%, blood glucose <60 or >400 mg/dL, weight gain >3kg in 24h OR >6kg in 14 days in a known heart failure patient WITH concurrent symptoms (oedema, dyspnoea). CRITICAL alerts must set escalate_immediately = true.
- URGENT: Sustained abnormal values over 2+ readings, or values exceeding threshold significantly, or a combination of threshold breach AND a known high-risk clinical factor (e.g., documented allergy conflict, confirmed medication discontinuation). Requires clinical response within hours to 1 day.
- ROUTINE: Single threshold breach with no trend, no high-risk factors, no concurrent symptoms. Requires scheduled follow-up.
- INFORMATIONAL: Values near threshold with a clear, documented contextual explanation. No immediate action required.

ESCALATION MODIFIER: If the alert involves a patient with a documented ALLERGY to the substance or medication class implicated in the alert context, upgrade urgency by one level regardless of the raw values.

MULTI-MEASUREMENT ALERTS: When both components of a paired measurement breach threshold simultaneously (e.g., systolic AND diastolic BP both exceeding their respective thresholds), classify based on the HIGHER-severity component and note both breaches in the urgency_rationale.

DYNAMIC TIME WINDOW — set time_window_months based on urgency:
- Critical: 24 months
- Urgent: 12 months
- Routine: 6 months
- Informational: 3 months
For patients with chronic conditions (heart failure, CKD), add 6 months to these defaults.

CHAIN-OF-THOUGHT PROCESS (work through before producing output):
1. What is the measurement and how far does it deviate from baseline and threshold?
2. Is this a single reading or a trend (review recent_readings carefully)?
3. Does the alert involve both components of a paired measurement?
4. Are there any high-risk modifiers that warrant urgency escalation?
5. What urgency level does this justify, including modifiers?
6. What time window is appropriate given urgency and likely conditions?
7. What should the EHR agent specifically search for?
8. What should the Anamnesis agent prioritise?

OUTPUT FORMAT: Return valid JSON only. No text outside the JSON.

{
  "urgency": "Critical | Urgent | Routine | Informational",
  "urgency_rationale": "2-4 sentences citing specific values, trends, and any escalation modifiers applied",
  "clinical_question": "Plain English summary of the clinical concern for downstream agents",
  "ehr_query_parameters": {
    "patient_id": "string",
    "relevant_conditions": ["list"],
    "relevant_medications": ["list"],
    "relevant_labs": ["list"],
    "time_window_months": 12
  },
  "anamnesis_query_parameters": {
    "patient_id": "string",
    "focus_areas": ["medication_adherence", "symptoms", "lifestyle", "family_history"],
    "clinical_question": "string"
  },
  "escalate_immediately": false,
  "escalation_modifiers_applied": ["list or empty array"]
}"""


# ── Agent class ───────────────────────────────────────────────────────────────

class TriageAgent:
    """
    Alert Triage Agent.
    Classifies RPM alert urgency and formulates structured retrieval queries
    for the EHR and Anamnesis agents.
    """

    def __init__(self):
        self.llm = ChatOpenAI(
            model="gpt-4o",
            temperature=0.0,         # Deterministic — classification requires consistency
            model_kwargs={"response_format": {"type": "json_object"}},
        )
        self.prompt_version = "v2"

    def _build_user_message(self, alert: dict) -> str:
        """Format the RPM alert as a structured input message."""
        recent = alert.get("recent_readings", [])
        recent_str = " → ".join(str(r) for r in recent) if recent else "No prior readings"

        return f"""Classify this RPM alert and formulate retrieval queries.

ALERT DATA:
- Patient ID: {alert.get('patient_id')}
- Timestamp: {alert.get('timestamp')}
- Device type: {alert.get('device_type')}
- Measurement: {alert.get('measurement_type')}
- Current value: {alert.get('value')} {alert.get('unit')}
- Patient baseline: {alert.get('baseline')} {alert.get('unit')}
- Alert threshold: {alert.get('alert_threshold')} {alert.get('unit')}
- Device alert category: {alert.get('alert_category')}
- Recent readings (oldest → newest): {recent_str}

Additional context: {alert.get('notes', 'None provided')}

Work through your chain-of-thought steps and produce the JSON output."""

    def run(self, alert: dict) -> dict:
        """
        Run the triage agent on an RPM alert.

        Args:
            alert: Dict containing RPM alert data (patient_id, values, thresholds, etc.)

        Returns:
            Dict with urgency classification and retrieval queries.
        """
        messages = [
            SystemMessage(content=TRIAGE_SYSTEM_PROMPT),
            HumanMessage(content=self._build_user_message(alert)),
        ]

        response = self.llm.invoke(messages)

        try:
            result = json.loads(response.content)
        except json.JSONDecodeError as e:
            # Fallback — should not occur with JSON mode enabled
            raise ValueError(f"Triage Agent returned invalid JSON: {e}\nRaw: {response.content}")

        # Validate urgency is one of the expected values
        valid_urgencies = {"Critical", "Urgent", "Routine", "Informational"}
        if result.get("urgency") not in valid_urgencies:
            raise ValueError(f"Triage Agent returned invalid urgency: {result.get('urgency')}")

        # Add metadata
        result["_meta"] = {
            "agent":          "TriageAgent",
            "prompt_version": self.prompt_version,
            "timestamp":      datetime.utcnow().isoformat(),
            "alert_input":    alert,
        }

        return result


# ── Convenience function ──────────────────────────────────────────────────────

def run_triage(alert: dict) -> dict:
    """Convenience wrapper for the TriageAgent."""
    agent = TriageAgent()
    return agent.run(alert)

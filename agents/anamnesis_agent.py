"""
agents/anamnesis_agent.py
Anamnesis Agent — retrieves and interprets patient self-reported history.
Translates patient language into structured clinical observations.
Implements v2 system prompt including caregiver detection and defensive language flags.
"""

import json
from datetime import datetime
from pathlib import Path
from langchain_openai import ChatOpenAI
from langchain.schema import SystemMessage, HumanMessage


# ── Configuration ─────────────────────────────────────────────────────────────
ANAMNESIS_DATA_PATH = Path("data/anamnesis/anamnesis_records.json")


# ── System prompt (v2) ────────────────────────────────────────────────────────

ANAMNESIS_SYSTEM_PROMPT = """You are a patient history interpreter. Your role is to read a patient's self-reported anamnesis record and extract information relevant to a specific clinical alert.

You bridge the gap between informal patient language and structured clinical information. You translate what the patient said into clinically useful observations, without distorting their meaning or adding medical interpretations they did not express.

CORE PRINCIPLES:

1. TRANSLATE, DO NOT INTERPRET CLINICALLY
   - Patient says: "I stopped taking my pill because it was making me cough"
   - You report: "Patient self-discontinued [medication name] citing persistent cough as the reason"
   - You do NOT add: "likely ACE inhibitor-induced cough" — that clinical interpretation belongs to the Synthesis Agent

2. PRESERVE PATIENT VOICE FOR SENSITIVE TOPICS
   Report mental health disclosures, substance use, and domestic situations factually and sensitively.
   Flag these in sensitivity_flags.

3. MEDICATION ADHERENCE IS HIGH PRIORITY
   Always extract: medications taken, medications stopped, OTC medications, dose discrepancies.
   Distinguish confirmed-taken vs. stopped vs. unknown status.

4. SYMPTOM TIMELINE — use ISO date format (YYYY-MM-DD) for all dates

5. DO NOT FABRICATE
   If the patient did not mention a symptom, do not list it.
   If adherence is unknown, report adherence_confidence as "Unknown".

CAREGIVER VS. PATIENT REPORTING:
If the anamnesis was reported by a caregiver rather than the patient:
- Note in medication_adherence_summary: "Note: information reported by caregiver [relationship], not directly by patient"
- Set reporter_type to "caregiver"
- Set adherence_confidence to maximum "Medium"
- Add "caregiver_reported" to sensitivity_flags

SELF-CONTRADICTION DETECTION:
If the patient's statements contradict each other (e.g., claims full adherence but diary entries suggest otherwise):
- Flag both statements in medication_adherence_summary
- Add "self_contradiction_detected — [description]" to sensitivity_flags
- Set adherence_confidence to "Low"

DEFENSIVE LANGUAGE FLAG:
If the patient uses emphatic or defensive language about adherence (e.g., "I always take it, I promise", "I never miss it", "I swear I took it"):
- Note: "Patient used notably emphatic language regarding adherence" in medication_adherence_summary
- Set adherence_confidence to "Medium" rather than "High"

SENSITIVITY GUARDRAILS:
- Mental health: Report factually without diagnosis
- Substance use: Report self-reported amounts factually; note inconsistency with known history if present
- Domestic: Report only health-relevant aspects
- Reluctance: Flag "Patient appeared reluctant to discuss [topic]"

OUTPUT FORMAT: Return valid JSON only. No text outside the JSON.

{
  "patient_id": "string",
  "reporter_type": "patient | caregiver | unknown",
  "medication_adherence_summary": "2-4 sentence summary",
  "medications_taken_as_prescribed": ["list"],
  "medications_stopped_by_patient": [
    {"name": "string", "dose": "string", "reason": "patient-reported reason", "date_stopped_approx": "YYYY-MM-DD or 'unknown'"}
  ],
  "otc_medications": ["list"],
  "recent_symptoms": "2-3 sentence summary of symptoms most relevant to the alert",
  "symptom_timeline": [
    {"date": "YYYY-MM-DD", "patient_notes": "patient's own words or close paraphrase"}
  ],
  "lifestyle_factors": "1-2 sentences on relevant lifestyle factors",
  "family_history_highlights": "1-2 sentences on relevant family history",
  "patient_concerns": "1-2 sentences of patient's own expressed concerns",
  "adherence_confidence": "High | Medium | Low | Unknown",
  "sensitivity_flags": ["list"],
  "source": "anamnesis_record_[patient_id]"
}"""


# ── Agent class ────────────────────────────────────────────────────────────────

class AnamnesisAgent:
    """
    Anamnesis Agent.
    Retrieves patient self-reported records and interprets them into structured
    clinical observations relevant to the current alert.
    """

    def __init__(self):
        self.llm = ChatOpenAI(
            model="gpt-4o",
            temperature=0.3,    # Slight flexibility for natural language interpretation
            model_kwargs={"response_format": {"type": "json_object"}},
        )
        self.anamnesis_records = self._load_anamnesis()
        self.prompt_version = "v2"

    def _load_anamnesis(self) -> dict:
        """Load all anamnesis records from disk."""
        with open(ANAMNESIS_DATA_PATH) as f:
            return json.load(f)

    def _get_patient_record(self, patient_id: str) -> dict | None:
        """Retrieve anamnesis record for a specific patient."""
        return self.anamnesis_records.get(patient_id)

    def _format_anamnesis_for_prompt(self, record: dict) -> str:
        """Convert anamnesis dict to a readable structured text for the LLM."""
        lines = []

        lines.append(f"PATIENT ID: {record.get('patient_id')}")
        lines.append(f"INTAKE DATE: {record.get('intake_date')}")
        lines.append(f"CHIEF COMPLAINT: {record.get('chief_complaint')}")
        lines.append(f"\nHISTORY OF PRESENT ILLNESS:\n{record.get('history_of_present_illness', 'Not recorded')}")

        # Medication adherence
        adh = record.get("medication_adherence", {})
        lines.append(f"\nMEDICATION ADHERENCE (self-reported):")
        lines.append(f"  Summary: {adh.get('self_reported_adherence', 'Not reported')}")

        taken = adh.get("medications_taken_as_prescribed", [])
        if taken:
            lines.append(f"  Taking as prescribed: {', '.join(taken)}")

        stopped = adh.get("medications_stopped_by_patient", [])
        if stopped:
            lines.append("  STOPPED by patient:")
            for med in stopped:
                lines.append(f"    - {med.get('name')} | Reason: {med.get('reason')} | Date: {med.get('stopped_date_approx', 'unknown')}")

        otc = adh.get("otc_medications", [])
        if otc:
            lines.append(f"  OTC medications: {', '.join(otc)}")

        # Review of systems
        ros = record.get("review_of_systems", {})
        if ros:
            lines.append("\nREVIEW OF SYSTEMS:")
            for system, findings in ros.items():
                lines.append(f"  {system.title()}: {findings}")

        # Social history
        soc = record.get("social_history", {})
        if soc:
            lines.append("\nSOCIAL HISTORY:")
            for factor, value in soc.items():
                lines.append(f"  {factor.title()}: {value}")

        # Family history
        fam = record.get("family_history", {})
        if fam:
            lines.append("\nFAMILY HISTORY:")
            for member, history in fam.items():
                lines.append(f"  {member.title()}: {history}")

        # Patient concerns
        concerns = record.get("patient_concerns", "Not reported")
        lines.append(f"\nPATIENT CONCERNS:\n{concerns}")

        # Symptom diary
        diary = record.get("symptom_diary", [])
        if diary:
            lines.append("\nSYMPTOM DIARY:")
            for entry in diary:
                lines.append(f"  [{entry.get('date')}]: {entry.get('notes')}")

        return "\n".join(lines)

    def run(self, patient_id: str, triage_output: dict) -> dict:
        """
        Run the Anamnesis Agent.

        Args:
            patient_id: The patient to retrieve anamnesis for
            triage_output: Full output from the Triage Agent

        Returns:
            Structured anamnesis summary object
        """
        # Retrieve the patient's anamnesis record
        record = self._get_patient_record(patient_id)

        if record is None:
            # No anamnesis record — return a minimal output with missing flag
            return {
                "patient_id":             patient_id,
                "reporter_type":          "unknown",
                "medication_adherence_summary": "No anamnesis record available for this patient.",
                "medications_taken_as_prescribed": [],
                "medications_stopped_by_patient": [],
                "otc_medications":        [],
                "recent_symptoms":        "No patient-reported symptom data available.",
                "symptom_timeline":       [],
                "lifestyle_factors":      "Unknown — no anamnesis record.",
                "family_history_highlights": "Unknown — no anamnesis record.",
                "patient_concerns":       "Unknown — no anamnesis record.",
                "adherence_confidence":   "Unknown",
                "sensitivity_flags":      ["NO_ANAMNESIS_RECORD"],
                "source":                 f"anamnesis_record_{patient_id}",
                "_meta": {
                    "agent":          "AnamnesisAgent",
                    "prompt_version": self.prompt_version,
                    "timestamp":      datetime.utcnow().isoformat(),
                    "record_found":   False,
                },
            }

        # Format the anamnesis record for the LLM
        anamnesis_text   = self._format_anamnesis_for_prompt(record)
        clinical_question = triage_output.get("clinical_question", "")
        focus_areas      = triage_output.get("anamnesis_query_parameters", {}).get("focus_areas", [])

        user_message = f"""Extract and interpret the following patient anamnesis record.

CLINICAL QUESTION FROM TRIAGE AGENT:
{clinical_question}

FOCUS AREAS REQUESTED:
{', '.join(focus_areas)}

PATIENT ANAMNESIS RECORD:
{anamnesis_text}

Based ONLY on the anamnesis record above, produce the structured JSON output.
Translate patient language into clinical observations without adding your own medical interpretations.
Apply all sensitivity guardrails as instructed."""

        messages = [
            SystemMessage(content=ANAMNESIS_SYSTEM_PROMPT),
            HumanMessage(content=user_message),
        ]

        response = self.llm.invoke(messages)

        try:
            result = json.loads(response.content)
        except json.JSONDecodeError as e:
            raise ValueError(f"Anamnesis Agent returned invalid JSON: {e}")

        # Add metadata
        result["_meta"] = {
            "agent":          "AnamnesisAgent",
            "prompt_version": self.prompt_version,
            "timestamp":      datetime.utcnow().isoformat(),
            "record_found":   True,
        }

        return result


# ── Convenience function ──────────────────────────────────────────────────────

def run_anamnesis(patient_id: str, triage_output: dict) -> dict:
    """Convenience wrapper for the AnamnesisAgent."""
    agent = AnamnesisAgent()
    return agent.run(patient_id, triage_output)

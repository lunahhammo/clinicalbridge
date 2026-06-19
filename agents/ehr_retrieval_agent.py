"""
agents/ehr_retrieval_agent.py
EHR Retrieval Agent — searches ChromaDB vector store and extracts relevant
patient history using RAG. Implements anti-hallucination guardrails, staleness
detection, and confidence scoring rubric from v2 system prompt.
"""

import json
from datetime import datetime, date
from pathlib import Path
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_community.vectorstores import Chroma
from langchain.schema import SystemMessage, HumanMessage


# ── Configuration ─────────────────────────────────────────────────────────────
CHROMA_DIR       = Path("data/chroma_db")
COLLECTION_NAME  = "clinicalbridge_ehr"
EMBEDDING_MODEL  = "text-embedding-3-small"
RETRIEVAL_TOP_K  = 8     # Number of chunks to retrieve per query
SIM_THRESHOLD    = 0.70  # Minimum similarity score to include a chunk
STALENESS_DAYS   = 90    # Labs older than this are flagged as potentially outdated


# ── System prompt (v2) ────────────────────────────────────────────────────────

EHR_SYSTEM_PROMPT = """You are a clinical data analyst. Your role is to search a patient's Electronic Health Record and extract information relevant to a specific clinical alert.

You are NOT a clinician. You extract and organise factual information from records. You do not make clinical interpretations or recommendations.

CRITICAL RULE: Only report information present in the retrieved EHR documents provided to you. If information is absent, flag it as missing. Never infer, assume, or fabricate clinical facts.

EXTRACTION PRIORITIES (in order):
1. Allergy alerts — always check for allergies relevant to the alert context, implicated medications, or potential treatments
2. Active medications — prescribed medications; note direct relevance to the alert type
3. Relevant diagnoses — problem list entries relevant to the alert
4. Recent lab results — values, dates, units, flags; note staleness per the STALENESS RULE below
5. Pertinent visit notes — 1-3 sentence excerpts directly relevant to the alert
6. Pattern flags — when two or more findings together form a clinically notable co-occurrence, flag it; do NOT interpret clinically — just note the co-occurrence
7. Missing data — explicitly list expected but absent information

STALENESS RULE: Any lab result dated more than 90 days before today's date must have "[POTENTIALLY OUTDATED — X days since collection]" appended to the flag field.

CONFIDENCE SCORING RUBRIC (score retrieval_confidence 0.0–1.0):
- 0.9–1.0: Comprehensive records; relevant data found for all query parameters; no major gaps
- 0.7–0.89: Good records; relevant data found for most query parameters; 1-2 minor gaps
- 0.5–0.69: Moderate records; some relevant data found; several gaps
- 0.3–0.49: Sparse records; limited relevant data; significant gaps
- 0.0–0.29: Minimal records; almost no relevant data
When confidence is below 0.5, include "LOW EHR CONFIDENCE — synthesis will rely heavily on anamnesis data" in missing_data_flags.

ANTI-HALLUCINATION RULES:
- Only report information in the retrieved document chunks below
- If a lab test is not in the chunks, list it under missing_data_flags: "Lab [name] not found in retrieved records"
- If two visit notes document conflicting information, report both with their dates; do not resolve the conflict
- Stale labs: flag with POTENTIALLY OUTDATED marker — do not omit them

OUTPUT FORMAT: Return valid JSON only. No text outside the JSON.

{
  "patient_id": "string",
  "relevant_diagnoses": [
    {"icd10": "code", "description": "string", "onset": "date", "status": "active|resolved"}
  ],
  "relevant_medications": [
    {"name": "string", "dose": "string", "frequency": "string", "indication": "string", "source": "section_name"}
  ],
  "relevant_labs": [
    {"test": "string", "value": "value", "unit": "string", "date": "date", "flag": "H|L|normal — with staleness note if applicable", "source": "string"}
  ],
  "relevant_visit_notes": [
    {"date": "date", "provider": "string", "excerpt": "1-3 sentences directly relevant to the alert", "source": "visit_note_date"}
  ],
  "allergy_alerts": [
    {"substance": "string", "reaction": "string", "severity": "string", "relevance_to_alert": "string"}
  ],
  "pattern_flags": [
    {"pattern": "string description", "findings": ["list"], "note": "Pattern flagged for clinician attention — clinical significance to be determined by physician"}
  ],
  "retrieval_confidence": 0.0,
  "missing_data_flags": ["list"],
  "source_references": ["list of document sections consulted"]
}"""


# ── Agent class ────────────────────────────────────────────────────────────────

class EHRRetrievalAgent:
    """
    EHR Retrieval Agent.
    Uses ChromaDB vector store (RAG) to retrieve relevant patient EHR sections,
    then uses GPT-4o to extract structured context from the retrieved chunks.
    """

    def __init__(self):
        self.llm = ChatOpenAI(
            model="gpt-4o",
            temperature=0.0,     # Factual extraction — no creativity needed
            model_kwargs={"response_format": {"type": "json_object"}},
        )
        self.embeddings = OpenAIEmbeddings(model=EMBEDDING_MODEL)
        self.vectorstore = self._load_vectorstore()
        self.prompt_version = "v2"

    def _load_vectorstore(self) -> Chroma:
        """Load the pre-built ChromaDB vector store."""
        if not CHROMA_DIR.exists():
            raise FileNotFoundError(
                f"Vector store not found at {CHROMA_DIR}. "
                "Please run: python setup_vectorstore.py"
            )
        return Chroma(
            collection_name=COLLECTION_NAME,
            embedding_function=self.embeddings,
            persist_directory=str(CHROMA_DIR),
        )

    def _retrieve_chunks(self, patient_id: str, query: str, k: int = RETRIEVAL_TOP_K) -> list:
        """
        Retrieve relevant EHR chunks for a patient using similarity search.
        Filters by patient_id to ensure only the correct patient's records are returned.
        """
        # Filter ensures we only retrieve chunks for the specific patient
        results = self.vectorstore.similarity_search_with_score(
            query=query,
            k=k,
            filter={"patient_id": patient_id},
        )

        # Apply similarity threshold filter
        filtered = [
            (doc, score)
            for doc, score in results
            if score >= SIM_THRESHOLD
        ]

        return filtered

    def _build_retrieval_query(self, triage_output: dict) -> str:
        """Build a retrieval query string from the triage agent's query parameters."""
        params = triage_output.get("ehr_query_parameters", {})
        conditions = ", ".join(params.get("relevant_conditions", []))
        medications = ", ".join(params.get("relevant_medications", []))
        labs       = ", ".join(params.get("relevant_labs", []))
        question   = triage_output.get("clinical_question", "")

        return (
            f"{question} "
            f"Relevant conditions: {conditions}. "
            f"Relevant medications: {medications}. "
            f"Relevant labs: {labs}."
        )

    def _format_chunks_for_prompt(self, chunks: list) -> str:
        """Format retrieved chunks into a structured string for the LLM prompt."""
        if not chunks:
            return "No EHR documents retrieved."

        formatted = []
        for i, (doc, score) in enumerate(chunks, 1):
            section  = doc.metadata.get("section", "unknown")
            pat_name = doc.metadata.get("patient_name", "unknown")
            formatted.append(
                f"[Chunk {i} | Section: {section} | Patient: {pat_name} | Similarity: {score:.3f}]\n"
                f"{doc.page_content}"
            )

        return "\n\n---\n\n".join(formatted)

    def _check_staleness(self, lab_date_str: str) -> str | None:
        """Return staleness note if lab date is older than STALENESS_DAYS, else None."""
        try:
            lab_date  = datetime.strptime(lab_date_str, "%Y-%m-%d").date()
            today     = date.today()
            days_old  = (today - lab_date).days
            if days_old > STALENESS_DAYS:
                return f"[POTENTIALLY OUTDATED — {days_old} days since collection]"
        except (ValueError, TypeError):
            pass
        return None

    def run(self, patient_id: str, triage_output: dict) -> dict:
        """
        Run the EHR Retrieval Agent.

        Args:
            patient_id: The patient to retrieve records for
            triage_output: Full output from the Triage Agent

        Returns:
            Structured EHR context object
        """
        # Build retrieval query from triage parameters
        query  = self._build_retrieval_query(triage_output)

        # Retrieve relevant EHR chunks from ChromaDB
        chunks = self._retrieve_chunks(patient_id, query)

        # Format chunks for the LLM
        chunks_text = self._format_chunks_for_prompt(chunks)

        # Build the clinical question context
        clinical_question = triage_output.get("clinical_question", "")
        time_window = triage_output.get("ehr_query_parameters", {}).get("time_window_months", 6)

        user_message = f"""Extract relevant EHR information for patient {patient_id}.

CLINICAL QUESTION FROM TRIAGE AGENT:
{clinical_question}

RETRIEVAL PARAMETERS:
- Time window: Last {time_window} months
- Focus areas: {triage_output.get('ehr_query_parameters', {}).get('relevant_conditions', [])}

RETRIEVED EHR DOCUMENT CHUNKS:
{chunks_text}

Total chunks retrieved: {len(chunks)}

Based ONLY on the retrieved document chunks above, produce the structured EHR context JSON.
Remember: if information is not in the chunks above, flag it as missing — do not infer it."""

        messages = [
            SystemMessage(content=EHR_SYSTEM_PROMPT),
            HumanMessage(content=user_message),
        ]

        response = self.llm.invoke(messages)

        try:
            result = json.loads(response.content)
        except json.JSONDecodeError as e:
            raise ValueError(f"EHR Retrieval Agent returned invalid JSON: {e}")

        # Post-process: add staleness markers to any lab results
        for lab in result.get("relevant_labs", []):
            lab_date = lab.get("date", "")
            staleness = self._check_staleness(lab_date)
            if staleness:
                current_flag = lab.get("flag", "unknown")
                lab["flag"] = f"{current_flag} {staleness}"

        # Add metadata
        result["_meta"] = {
            "agent":           "EHRRetrievalAgent",
            "prompt_version":  self.prompt_version,
            "timestamp":       datetime.utcnow().isoformat(),
            "chunks_retrieved": len(chunks),
            "retrieval_query": query,
        }

        return result


# ── Convenience function ──────────────────────────────────────────────────────

def run_ehr_retrieval(patient_id: str, triage_output: dict) -> dict:
    """Convenience wrapper for the EHRRetrievalAgent."""
    agent = EHRRetrievalAgent()
    return agent.run(patient_id, triage_output)

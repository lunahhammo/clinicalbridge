"""
setup_vectorstore.py
Run this ONCE before using ClinicalBridge to embed EHR documents into ChromaDB.
Usage: python setup_vectorstore.py
"""

import json
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

from langchain_openai import OpenAIEmbeddings
from langchain_community.vectorstores import Chroma
from langchain.schema import Document

# ── Configuration ───────────────────────────────────────────────────────────
EHR_DATA_PATH   = Path("data/ehr/patients_ehr.json")
CHROMA_DIR      = Path("data/chroma_db")
COLLECTION_NAME = "clinicalbridge_ehr"
EMBEDDING_MODEL = "text-embedding-3-small"   # Cost-efficient, good clinical text retrieval

# ── EHR chunking strategy ────────────────────────────────────────────────────
# Semantic chunking: each EHR section becomes its own document chunk.
# This preserves the meaning of each section and prevents mixing of e.g.
# medication lists with visit notes in a single chunk.


def chunk_ehr_record(patient: dict) -> list[Document]:
    """
    Convert one patient EHR record into a list of semantically-chunked Documents.
    Each section (demographics, problem_list, medications, labs, visit_notes, allergies)
    becomes its own Document with metadata identifying its type and patient.
    """
    chunks = []
    pid    = patient["patient_id"]
    name   = patient["demographics"]["name"]
    base_meta = {
        "patient_id":   pid,
        "patient_name": name,
        "scenario_tag": patient.get("scenario_tag", "general"),
    }

    # ── 1. Demographics chunk ────────────────────────────────────────────────
    d = patient["demographics"]
    demo_text = (
        f"Patient: {d['name']} | DOB: {d['dob']} | Age: {d['age']} | "
        f"Sex: {d['sex']} | Weight: {d['weight_kg']}kg | Height: {d['height_cm']}cm"
    )
    chunks.append(Document(
        page_content=demo_text,
        metadata={**base_meta, "section": "demographics"},
    ))

    # ── 2. Problem list chunk ────────────────────────────────────────────────
    problems = patient.get("problem_list", [])
    if problems:
        problem_lines = [
            f"- {p['description']} (ICD-10: {p['icd10']}, onset: {p['onset']}, status: {p['status']})"
            for p in problems
        ]
        chunks.append(Document(
            page_content=f"Problem list for {name}:\n" + "\n".join(problem_lines),
            metadata={**base_meta, "section": "problem_list"},
        ))

    # ── 3. Medications chunk ─────────────────────────────────────────────────
    meds = patient.get("medications", [])
    if meds:
        med_lines = [
            f"- {m['name']} {m['dose']} {m['frequency']} for {m['indication']} (prescribed: {m['prescribed']})"
            for m in meds
        ]
        chunks.append(Document(
            page_content=f"Medications for {name}:\n" + "\n".join(med_lines),
            metadata={**base_meta, "section": "medications"},
        ))

    # ── 4. Allergies chunk ───────────────────────────────────────────────────
    allergies = patient.get("allergies", [])
    if allergies:
        allergy_lines = [
            f"- ALLERGY: {a['substance']} → Reaction: {a['reaction']} (Severity: {a['severity']})"
            for a in allergies
        ]
        chunks.append(Document(
            page_content=f"Allergy record for {name}:\n" + "\n".join(allergy_lines),
            metadata={**base_meta, "section": "allergies"},
        ))
    else:
        chunks.append(Document(
            page_content=f"Allergy record for {name}: No known allergies documented.",
            metadata={**base_meta, "section": "allergies"},
        ))

    # ── 5. Lab results chunk ─────────────────────────────────────────────────
    labs = patient.get("lab_results", [])
    if labs:
        lab_lines = [
            f"- {l['test']}: {l['value']} {l['unit']} (date: {l['date']}, flag: {l['flag']}, ref: {l['reference_range']})"
            for l in labs
        ]
        chunks.append(Document(
            page_content=f"Lab results for {name}:\n" + "\n".join(lab_lines),
            metadata={**base_meta, "section": "lab_results"},
        ))

    # ── 6. Visit notes — one chunk per note ──────────────────────────────────
    for note in patient.get("visit_notes", []):
        note_text = (
            f"Visit note for {name} ({note['date']}) | Provider: {note['provider']} | "
            f"Type: {note['type']}\n{note['note']}"
        )
        chunks.append(Document(
            page_content=note_text,
            metadata={
                **base_meta,
                "section": "visit_note",
                "note_date": note["date"],
                "provider":  note["provider"],
            },
        ))

    return chunks


def build_vectorstore() -> None:
    print("=== ClinicalBridge Vector Store Setup ===\n")

    # Load EHR JSON
    print(f"Loading EHR records from {EHR_DATA_PATH}...")
    with open(EHR_DATA_PATH) as f:
        patients = json.load(f)
    print(f"  Loaded {len(patients)} patient records.")

    # Chunk all records
    all_chunks: list[Document] = []
    for patient in patients:
        patient_chunks = chunk_ehr_record(patient)
        all_chunks.extend(patient_chunks)
        print(f"  PT{patient['patient_id'][-3:]} ({patient['demographics']['name']}): "
              f"{len(patient_chunks)} chunks")

    print(f"\nTotal chunks to embed: {len(all_chunks)}")

    # Embed and store
    print(f"\nInitialising embeddings ({EMBEDDING_MODEL})...")
    embeddings = OpenAIEmbeddings(model=EMBEDDING_MODEL)

    print(f"Building ChromaDB at {CHROMA_DIR}...")
    CHROMA_DIR.mkdir(parents=True, exist_ok=True)

    vectorstore = Chroma.from_documents(
        documents=all_chunks,
        embedding=embeddings,
        collection_name=COLLECTION_NAME,
        persist_directory=str(CHROMA_DIR),
    )

    print(f"\n✓ Vector store built successfully.")
    print(f"  Collection: {COLLECTION_NAME}")
    print(f"  Location:   {CHROMA_DIR}")
    print(f"  Documents:  {len(all_chunks)} chunks across {len(patients)} patients")
    print("\nYou can now run: python main.py --scenario [1-5]")


if __name__ == "__main__":
    build_vectorstore()

"""
ontology/ontology_lookup.py
----------------------------
Ontology lookup with two interchangeable strategies:

  1. FAISS (default) — vector similarity search over the pre-built index.
     Fast (<0.1s), scales to thousands of terms, handles synonyms.
     Requires: python ontology/build_vector_db.py to be run first.

  2. Vector-less RAG — passes the full ontology list directly in the Ollama
     prompt and asks the LLM to pick the best match.
     Simpler, no index required, but slower and only practical for small
     ontologies (< ~100 terms).

Strategy is controlled by config/settings.py -> ONTOLOGY_STRATEGY.
Can also be overridden per-call: lookup("asthma", strategy="vectorless")

Usage:
    from ontology.ontology_lookup import lookup

    results = lookup("breast cancer", top_k=1)
    # -> [OntologyMatch(code="NCIT:C2985", label="breast carcinoma", similarity=0.88)]
"""

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config.settings import (
    EMBEDDING_MODEL, FAISS_INDEX_PATH, OLLAMA_BASE_URL,
    OLLAMA_MODEL, ONTOLOGY_META_PATH, ONTOLOGY_STRATEGY,
)

# Module-level cache for FAISS resources — loaded once, reused forever
_cache: Optional[tuple] = None


@dataclass
class OntologyMatch:
    """A single result from an ontology lookup."""
    code:       str    # e.g. "NCIT:C2985"
    label:      str    # e.g. "breast carcinoma"
    similarity: float  # 0.0–1.0 (cosine similarity or LLM confidence)
    strategy:   str = "faiss"  # which strategy produced this result


def _load_faiss_resources() -> tuple:
    """Load FAISS index, metadata, and embedding model. Cached after first call."""
    global _cache
    if _cache is not None:
        return _cache

    try:
        import faiss
        from sentence_transformers import SentenceTransformer
    except ImportError:
        raise ImportError(
            "Missing packages. Run: pip install faiss-cpu sentence-transformers"
        )

    if not FAISS_INDEX_PATH.exists():
        raise FileNotFoundError(
            f"FAISS index not found at {FAISS_INDEX_PATH}.\n"
            "Run: python ontology/build_vector_db.py"
        )
    if not ONTOLOGY_META_PATH.exists():
        raise FileNotFoundError(
            f"Ontology metadata not found at {ONTOLOGY_META_PATH}.\n"
            "Run: python ontology/build_vector_db.py"
        )

    index = faiss.read_index(str(FAISS_INDEX_PATH))
    with open(ONTOLOGY_META_PATH) as f:
        meta = json.load(f)
    model = SentenceTransformer(EMBEDDING_MODEL)

    _cache = (index, meta, model)
    return _cache


def _lookup_faiss(query: str, top_k: int) -> list[OntologyMatch]:
    """FAISS cosine similarity search."""
    index, meta, model = _load_faiss_resources()

    vec = model.encode([query.lower()], normalize_embeddings=True)
    vec = np.array(vec, dtype="float32")

    scores, indices = index.search(vec, top_k)

    results: list[OntologyMatch] = []
    for score, idx in zip(scores[0], indices[0]):
        if score < 0.5 or idx < 0:
            continue
        results.append(OntologyMatch(
            code=meta[idx]["code"],
            label=meta[idx]["label"],
            similarity=float(score),
            strategy="faiss",
        ))
    return results


def _load_ontology_list() -> str:
    """
    Load the ontology terms as a plain text list for prompt injection.
    Returns a compact string like: "NCIT:C20197=male, NCIT:C16576=female, ..."
    """
    if not ONTOLOGY_META_PATH.exists():
        raise FileNotFoundError(
            f"Ontology metadata not found at {ONTOLOGY_META_PATH}.\n"
            "Run: python ontology/build_vector_db.py"
        )
    with open(ONTOLOGY_META_PATH) as f:
        meta = json.load(f)

    # Deduplicate by code (meta has one entry per text variation)
    seen: set[str] = set()
    lines: list[str] = []
    for entry in meta:
        if entry["code"] not in seen:
            lines.append(f"{entry['code']}={entry['label']}")
            seen.add(entry["code"])
    return ", ".join(lines)


def _lookup_vectorless(query: str, top_k: int) -> list[OntologyMatch]:
    """
    Vector-less RAG: pass ontology list to Ollama, ask it to pick best match.

    Pros: no FAISS index needed, LLM understands synonyms natively.
    Cons: slower (~2s per lookup), only practical for small ontologies.
    """
    import requests

    ontology_list = _load_ontology_list()

    system = (
        "You are a biomedical ontology expert. "
        "Given a search term and a list of ontology codes, find the best matching code.\n"
        "Reply with ONLY a JSON object: "
        '{"code": "CODE:XXXXXX", "label": "matched label", "confidence": 0.0-1.0}\n'
        "If no good match exists, reply: "
        '{"code": null, "label": null, "confidence": 0.0}\n'
        "Do not add any explanation."
    )
    prompt = (
        f'Search term: "{query}"\n\n'
        f"Available ontology codes:\n{ontology_list}\n\n"
        f"Best match:"
    )

    try:
        resp = requests.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "system": system,
                "stream": False,
                "options": {"temperature": 0.0},
            },
            timeout=30,
        )
        resp.raise_for_status()
        raw = resp.json()["response"].strip()

        m = re.search(r"\{[^}]+\}", raw)
        if not m:
            return []
        data = json.loads(m.group())

        if not data.get("code") or data["confidence"] < 0.4:
            return []

        return [OntologyMatch(
            code=data["code"],
            label=data.get("label", ""),
            similarity=float(data["confidence"]),
            strategy="vectorless",
        )]
    except Exception:
        return []


def lookup(
    query: str,
    top_k: int = 1,
    strategy: str | None = None,
) -> list[OntologyMatch]:
    """
    Find the best matching ontology term(s) for a plain English query.

    Args:
        query:    Plain English medical term.
                  e.g. "breast cancer", "male", "Northern Ireland", "asthma"
        top_k:    How many results to return (default 1). Only used by FAISS.
        strategy: Override the global ONTOLOGY_STRATEGY setting.
                  "faiss" or "vectorless".

    Returns:
        List of OntologyMatch objects sorted by similarity descending.
        Empty list if no match meets the confidence threshold.

    Examples:
        lookup("male")             -> [OntologyMatch("NCIT:C20197", "male", 0.99)]
        lookup("breast cancer")    -> [OntologyMatch("NCIT:C2985", "breast carcinoma", 0.88)]
        lookup("Northern Ireland") -> [OntologyMatch("GAZ:00002638", "Northern Ireland", 1.0)]
        lookup("asthma", strategy="vectorless")  # use LLM instead of FAISS
    """
    strat = strategy or ONTOLOGY_STRATEGY

    if strat == "vectorless":
        return _lookup_vectorless(query, top_k)
    else:
        return _lookup_faiss(query, top_k)


if __name__ == "__main__":
    print("FAISS strategy:")
    tests = ["male", "female", "breast cancer", "asthma", "Northern Ireland",
             "European", "brain", "missense variant", "regional failure"]
    for q in tests:
        r = lookup(q, top_k=1, strategy="faiss")
        tag = f"{r[0].code} ({r[0].label}) [{r[0].similarity:.4f}]" if r else "no match"
        print(f"  '{q}' -> {tag}")
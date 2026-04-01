"""
tools/ontology_tool.py
----------------------
Legacy CrewAI tool wrapper for ontology lookup.

STATUS: Not used by the current agents (beacon_agent.py calls lookup() directly).
Kept for reference — useful if you want to expose ontology lookup as a formal
CrewAI tool with args_schema for agents 3 or 4.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ontology.ontology_lookup import OntologyMatch, lookup


def find_ontology_code(term: str, top_k: int = 3) -> list[dict]:
    """
    Find ontology codes for a plain English medical term.

    Args:
        term:  Plain English string, e.g. "breast cancer", "male", "asthma"
        top_k: Number of results to return (default 3)

    Returns:
        List of dicts with keys: code, label, similarity
        Empty list if no match meets the 0.5 similarity threshold.

    Examples:
        find_ontology_code("breast cancer")
        -> [{"code": "NCIT:C2985", "label": "breast carcinoma", "similarity": 0.88}]

        find_ontology_code("male")
        -> [{"code": "NCIT:C20197", "label": "male", "similarity": 0.99}]
    """
    results: list[OntologyMatch] = lookup(term, top_k=top_k)
    return [
        {"code": r.code, "label": r.label, "similarity": round(r.similarity, 4)}
        for r in results
    ]


if __name__ == "__main__":
    # Quick test
    for term in ["male", "breast cancer", "asthma", "European", "Northern Ireland"]:
        codes = find_ontology_code(term, top_k=1)
        if codes:
            c = codes[0]
            print(f"'{term}' -> {c['code']} ({c['label']}) [{c['similarity']}]")
        else:
            print(f"'{term}' -> no match")
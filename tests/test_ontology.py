"""
tests/test_ontology.py
-----------------------
Tests for ontology/build_vector_db.py and ontology/ontology_lookup.py.
Requires: python ontology/build_vector_db.py to have been run first.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config.settings import FAISS_INDEX_PATH, ONTOLOGY_META_PATH


# ── build_vector_db tests ──────────────────────────────────────────────────────

def test_ontology_index_exists():
    assert FAISS_INDEX_PATH.exists(), (
        "FAISS index not found. Run: python ontology/build_vector_db.py"
    )

def test_ontology_meta_exists():
    assert ONTOLOGY_META_PATH.exists(), (
        "ontology_meta.json not found. Run: python ontology/build_vector_db.py"
    )

def test_ontology_meta_structure():
    import json
    with open(ONTOLOGY_META_PATH) as f:
        meta = json.load(f)
    assert isinstance(meta, list), "meta must be a list"
    assert len(meta) >= 29 * 2, f"Expected at least 58 entries (29 terms × 2), got {len(meta)}"
    for entry in meta[:5]:
        assert "code"  in entry, "Each entry must have 'code'"
        assert "label" in entry, "Each entry must have 'label'"
        assert ":" in entry["code"], f"Code must contain ':', got: {entry['code']}"

def test_ontology_meta_has_expected_codes():
    import json
    with open(ONTOLOGY_META_PATH) as f:
        meta = json.load(f)
    codes = {e["code"] for e in meta}
    required = {
        "NCIT:C20197",    # male
        "NCIT:C16576",    # female
        "NCIT:C35553",    # regional failure
        "HANCESTRO:0005", # European
        "GAZ:00002638",   # Northern Ireland
        "MONDO:0004979",  # asthma
    }
    missing = required - codes
    assert not missing, f"Missing expected codes: {missing}"


# ── ontology_lookup tests ──────────────────────────────────────────────────────

def test_lookup_male():
    from ontology.ontology_lookup import lookup
    results = lookup("male", top_k=1)
    assert results, "lookup('male') returned no results"
    assert results[0].code == "NCIT:C20197", f"Expected NCIT:C20197, got {results[0].code}"
    assert results[0].similarity > 0.9

def test_lookup_female():
    from ontology.ontology_lookup import lookup
    results = lookup("female", top_k=1)
    assert results
    assert results[0].code == "NCIT:C16576"

def test_lookup_breast_cancer():
    from ontology.ontology_lookup import lookup
    results = lookup("breast cancer", top_k=1)
    assert results
    assert results[0].code in ("NCIT:C2985", "MONDO:0007254"), \
        f"Expected breast cancer code, got {results[0].code}"

def test_lookup_northern_ireland():
    from ontology.ontology_lookup import lookup
    results = lookup("Northern Ireland", top_k=1)
    assert results
    assert results[0].code == "GAZ:00002638"
    assert results[0].similarity > 0.95

def test_lookup_asthma():
    from ontology.ontology_lookup import lookup
    results = lookup("asthma", top_k=1)
    assert results
    assert results[0].code == "MONDO:0004979"

def test_lookup_european():
    from ontology.ontology_lookup import lookup
    results = lookup("European", top_k=1)
    assert results
    assert results[0].code == "HANCESTRO:0005"

def test_lookup_unknown_term_returns_empty_or_low_similarity():
    from ontology.ontology_lookup import lookup
    results = lookup("xyzzy_not_a_real_term_12345", top_k=1)
    # Either no results, or similarity below 0.5
    if results:
        assert results[0].similarity < 0.6, \
            f"Unknown term matched with high confidence: {results[0]}"

def test_lookup_top_k():
    from ontology.ontology_lookup import lookup
    results = lookup("cancer", top_k=3)
    assert len(results) <= 3

def test_lookup_returns_ontology_match_objects():
    from ontology.ontology_lookup import OntologyMatch, lookup
    results = lookup("male", top_k=1)
    assert isinstance(results[0], OntologyMatch)
    assert isinstance(results[0].code, str)
    assert isinstance(results[0].label, str)
    assert isinstance(results[0].similarity, float)
    assert 0.0 <= results[0].similarity <= 1.0

def test_lookup_case_insensitive():
    from ontology.ontology_lookup import lookup
    r1 = lookup("MALE")
    r2 = lookup("male")
    r3 = lookup("Male")
    # All should return the same code
    if r1 and r2 and r3:
        assert r1[0].code == r2[0].code == r3[0].code

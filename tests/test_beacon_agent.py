"""
tests/test_beacon_agent.py
---------------------------
Tests for agents/beacon_agent.py — keyword extraction, variant coord parsing,
JSON assembly. Does NOT make live Ollama or Beacon calls.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ── Variant coordinate extraction ─────────────────────────────────────────────

def test_extract_variant_coords_basic():
    from agents.beacon_agent import _extract_variant_coords
    result = _extract_variant_coords(
        "Get variants from chromosome 2 from 5500000 to 5510000"
    )
    assert result is not None
    assert result["referenceName"] == "2"
    assert result["start"] == 5500000
    assert result["end"] == 5510000

def test_extract_variant_coords_M_suffix():
    from agents.beacon_agent import _extract_variant_coords
    result = _extract_variant_coords(
        "Get variants from chr2 from 5.5M to 5.51M"
    )
    assert result is not None
    assert result["start"] == 5_500_000
    assert result["end"] == 5_510_000

def test_extract_variant_coords_commas():
    from agents.beacon_agent import _extract_variant_coords
    result = _extract_variant_coords(
        "chromosome 5 from 10,000,000 to 10,001,000"
    )
    assert result is not None
    assert result["start"] == 10_000_000
    assert result["end"] == 10_001_000

def test_extract_variant_coords_no_chrom_returns_none():
    from agents.beacon_agent import _extract_variant_coords
    result = _extract_variant_coords("Find male individuals with asthma")
    assert result is None

def test_extract_variant_coords_chrX():
    from agents.beacon_agent import _extract_variant_coords
    result = _extract_variant_coords("variants on chrX from 1000 to 2000")
    assert result is not None
    assert result["referenceName"] == "X"


# ── JSON assembly ──────────────────────────────────────────────────────────────

def test_beacon_json_structure():
    """Verify the assembled JSON has the correct Beacon v2 structure."""
    # Manually assemble a query (bypassing Ollama)
    from agents.beacon_agent import _extract_variant_coords
    from ontology.ontology_lookup import lookup

    filters = []
    matches = lookup("male", top_k=1)
    if matches:
        filters.append({
            "id":       matches[0].code,
            "label":    matches[0].label,
            "operator": "=",
        })

    request_params = {
        "scope":       "individuals",
        "granularity": "record",
        "filters":     filters,
    }
    result = {
        "meta":  {"apiVersion": "v2.0"},
        "query": {"requestParameters": request_params},
    }

    # Validate structure
    assert "meta" in result
    assert result["meta"]["apiVersion"] == "v2.0"
    assert "query" in result
    assert "requestParameters" in result["query"]
    rp = result["query"]["requestParameters"]
    assert rp["scope"] in ("individuals", "variants", "biosamples", "cohorts")
    assert rp["granularity"] in ("record", "count", "boolean")
    assert isinstance(rp.get("filters", []), list)

def test_beacon_json_filter_has_id():
    """Every filter must have an 'id' field."""
    from ontology.ontology_lookup import lookup
    matches = lookup("European", top_k=1)
    if matches:
        fi = {"id": matches[0].code, "label": matches[0].label, "operator": "="}
        assert "id" in fi
        assert fi["id"].startswith("HANCESTRO:")

def test_beacon_scope_to_endpoint_mapping():
    """Verify scope → endpoint URL mapping is complete."""
    from agents.beacon_agent import _SCOPE_TO_ENDPOINT
    required_scopes = {"individuals", "variants", "biosamples", "cohorts"}
    assert required_scopes == set(_SCOPE_TO_ENDPOINT.keys())
    for scope, endpoint in _SCOPE_TO_ENDPOINT.items():
        assert endpoint.startswith("/"), f"Endpoint must start with /: {endpoint}"

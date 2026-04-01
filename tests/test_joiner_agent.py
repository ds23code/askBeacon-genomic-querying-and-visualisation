"""
tests/test_joiner_agent.py
---------------------------
Tests for agents/joiner_agent.py — CSV loading, JSON loading, join logic.
Uses in-memory test data — no file I/O required.
"""
import csv
import io
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ── Helper: write temp CSV ─────────────────────────────────────────────────────

def _write_temp_csv(rows: list[dict], tmp_dir: Path) -> Path:
    p = tmp_dir / "test_vcf.csv"
    with open(p, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return p


def _write_temp_json(data: dict, tmp_dir: Path) -> Path:
    p = tmp_dir / "test_beacon.txt"
    p.write_text(json.dumps(data, indent=2))
    return p


# ── Tests ──────────────────────────────────────────────────────────────────────

def test_load_vcf_csv():
    from agents.joiner_agent import _load_vcf_csv
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        rows = [
            {"CHROM": "2", "POS": "5500302", "ID": "rs10929519", "REF": "G", "ALT": "A"},
            {"CHROM": "2", "POS": "5500896", "ID": "rs201232433", "REF": "TA", "ALT": "T"},
        ]
        p = _write_temp_csv(rows, tmp)
        loaded = _load_vcf_csv(p)
        assert len(loaded) == 2
        assert loaded[0]["CHROM"] == "2"
        assert loaded[0]["POS"] == "5500302"

def test_load_beacon_json():
    from agents.joiner_agent import _load_beacon_json
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        data = {
            "meta": {"apiVersion": "v2.0"},
            "query": {
                "requestParameters": {
                    "scope": "individuals",
                    "granularity": "record",
                    "filters": [
                        {"id": "NCIT:C20197", "label": "male", "operator": "="},
                    ],
                }
            },
        }
        p = _write_temp_json(data, tmp)
        loaded = _load_beacon_json(p)
        assert loaded["meta"]["apiVersion"] == "v2.0"
        filters = loaded["query"]["requestParameters"]["filters"]
        assert len(filters) == 1
        assert filters[0]["id"] == "NCIT:C20197"

def test_extract_beacon_context():
    from agents.joiner_agent import _extract_beacon_context
    data = {
        "query": {
            "requestParameters": {
                "scope": "individuals",
                "granularity": "boolean",
                "filters": [
                    {"id": "HANCESTRO:0005", "label": "European", "operator": "="},
                    {"id": "NCIT:C2985", "label": "breast carcinoma", "operator": "="},
                ],
            }
        }
    }
    ctx = _extract_beacon_context(data)
    assert ctx["scope"] == "individuals"
    assert ctx["granularity"] == "boolean"
    assert "European" in ctx["filter_labels"]
    assert "breast carcinoma" in ctx["filter_labels"]
    assert "HANCESTRO:0005" in ctx["filter_codes"]

def test_join_datasets_annotates_all_rows():
    from agents.joiner_agent import _join_datasets
    vcf_rows = [
        {"CHROM": "2", "POS": "5500302", "ID": "rs10929519"},
        {"CHROM": "2", "POS": "5500896", "ID": "rs201232433"},
    ]
    beacon_ctx = {
        "scope": "individuals",
        "granularity": "record",
        "filter_labels": ["male", "regional failure"],
        "filter_codes":  ["NCIT:C20197", "NCIT:C35553"],
        "filter_summary": "male, regional failure",
        "variant_query": {},
    }
    joined = _join_datasets(vcf_rows, beacon_ctx)
    assert len(joined) == 2
    for row in joined:
        assert "beacon_scope" in row
        assert "beacon_filters" in row
        assert row["beacon_scope"] == "individuals"

def test_join_datasets_position_overlap():
    from agents.joiner_agent import _join_datasets
    vcf_rows = [
        {"CHROM": "2", "POS": "5500302"},
        {"CHROM": "5", "POS": "1000"},   # different chrom — no overlap
    ]
    beacon_ctx = {
        "scope": "variants",
        "granularity": "record",
        "filter_labels": [],
        "filter_codes":  [],
        "filter_summary": "no filters",
        "variant_query": {"referenceName": "2", "start": 5500000, "end": 5510000},
    }
    joined = _join_datasets(vcf_rows, beacon_ctx)
    assert joined[0]["beacon_position_overlap"] == "yes"
    assert joined[1]["beacon_position_overlap"] == "no"

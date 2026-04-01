"""
tests/test_settings.py
-----------------------
Tests for config/settings.py — verifies all paths and variables are correct.
Run with: python -m pytest tests/ -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config.settings import (
    BEACON_BASE_URL, DEFAULT_VCF_FILE, EMBEDDING_MODEL,
    FAISS_INDEX_PATH, GENOMES_S3_BASE, OLLAMA_BASE_URL,
    OLLAMA_MODEL, ONTOLOGY_META_PATH, ONTOLOGY_STRATEGY,
    OUTPUTS_DIR, ROOT_DIR, TEMPLATES_DIR,
)


def test_root_dir_exists():
    assert ROOT_DIR.exists(), f"ROOT_DIR not found: {ROOT_DIR}"

def test_templates_dir_exists():
    assert TEMPLATES_DIR.exists(), f"TEMPLATES_DIR not found: {TEMPLATES_DIR}"

def test_bcftools_template_exists():
    template = TEMPLATES_DIR / "bcftools_template.md"
    assert template.exists(), "bcftools_template.md not found"
    content = template.read_text()
    assert "bcftools view" in content
    assert "Template 1" in content

def test_outputs_dir_created():
    OUTPUTS_DIR.mkdir(exist_ok=True)
    assert OUTPUTS_DIR.exists()

def test_ollama_url_format():
    assert OLLAMA_BASE_URL.startswith("http"), "OLLAMA_BASE_URL must be an http URL"
    assert "11434" in OLLAMA_BASE_URL, "Default Ollama port is 11434"

def test_genomes_s3_base_format():
    assert "{chrom}" in GENOMES_S3_BASE, "GENOMES_S3_BASE must contain {chrom}"
    assert "s3://1000genomes" in GENOMES_S3_BASE

def test_default_vcf_file():
    assert DEFAULT_VCF_FILE.startswith("s3://")
    assert "chr1" in DEFAULT_VCF_FILE

def test_ontology_strategy_valid():
    assert ONTOLOGY_STRATEGY in ("faiss", "vectorless"), \
        f"ONTOLOGY_STRATEGY must be 'faiss' or 'vectorless', got: {ONTOLOGY_STRATEGY}"

def test_paths_are_path_objects():
    for name, val in [
        ("FAISS_INDEX_PATH", FAISS_INDEX_PATH),
        ("ONTOLOGY_META_PATH", ONTOLOGY_META_PATH),
        ("TEMPLATES_DIR", TEMPLATES_DIR),
        ("OUTPUTS_DIR", OUTPUTS_DIR),
        ("ROOT_DIR", ROOT_DIR),
    ]:
        assert isinstance(val, Path), f"{name} must be a Path object, got {type(val)}"

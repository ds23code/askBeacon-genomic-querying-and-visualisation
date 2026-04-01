"""
config/settings.py
------------------
Central configuration for the Genomic AI Agents project.
Change a value here and it updates everywhere automatically.
"""
from pathlib import Path

# Project root directory
ROOT_DIR = Path(__file__).resolve().parent.parent

# Ollama API settings
OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_MODEL    = "llama3"   # Swap to "llama3.1", "mistral", etc.

# sBeacon endpoint (demo instance)
# To fetch available ontology terms from the live endpoint:
#   curl -s 'https://beacon.demo.umccr.org/individuals/filtering_terms?limit=1000' | jq
BEACON_BASE_URL = "https://beacon.demo.umccr.org"

# 1000 Genomes S3 paths – bcftools streams directly from S3.
GENOMES_S3_BASE = (
    "s3://1000genomes/release/20130502/"
    "ALL.chr{chrom}.phase3_shapeit2_mvncall_integrated_v5a"
    ".20130502.genotypes.vcf.gz"
)
DEFAULT_VCF_FILE = GENOMES_S3_BASE.format(chrom=1)

# Paths (all Path objects – supports / operator and .exists())
FAISS_INDEX_PATH   = ROOT_DIR / "ontology" / "ontology.index"
ONTOLOGY_META_PATH = ROOT_DIR / "ontology" / "ontology_meta.json"
ONTOLOGY_META      = ONTOLOGY_META_PATH       # alias used by some imports
EMBEDDING_MODEL    = "all-MiniLM-L6-v2"       # sentence-transformers model

TEMPLATES_DIR      = ROOT_DIR / "templates"
OUTPUTS_DIR        = ROOT_DIR / "outputs"

# RAG strategy for ontology lookup
# "faiss"     — use FAISS vector similarity search (scales to thousands of terms)
# "vectorless"— pass the full ontology list in the Ollama prompt (simpler, fine
#               for small ontologies; less reliable for very large term sets)
ONTOLOGY_STRATEGY = "faiss"
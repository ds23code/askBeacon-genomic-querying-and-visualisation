"""
ontology/build_vector_db.py
----------------------------
One-time setup script. Run ONCE after cloning:

    python ontology/build_vector_db.py

What it does:
  1. Takes the ONTOLOGY_TERMS list (29 terms, ~150 entries including synonyms)
  2. Converts every entry to a 384-dim float vector using sentence-transformers
  3. Stores all vectors in a FAISS inner-product index saved as ontology.index
  4. Stores the corresponding {code, label} metadata in ontology_meta.json

Run again whenever you add new terms (e.g. after importing sBeacon terms.csv).

Ontology systems used:
  GAZ       — Gazetteer (geographic locations)
  MONDO     — Monarch Disease Ontology (diseases)
  NCIT      — NCI Thesaurus (sex, clinical terms)
  HANCESTRO — Human Ancestry Ontology (population ancestry)
  UBERON    — Uber Anatomy Ontology (tissue/organ types)
  SO        — Sequence Ontology (variant types)

To import terms from sBeacon terms.csv:
    python ontology/build_vector_db.py --import path/to/terms.csv
"""

import argparse
import csv
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# ── Core ontology terms ────────────────────────────────────────────────────────
ONTOLOGY_TERMS = [

    # Geographic (GAZ) — from CINECA UK1 dataset in sBeacon demo
    {"code": "GAZ:00002638", "label": "Northern Ireland",
     "synonyms": ["north ireland", "northern ireland", "ulster"]},
    {"code": "GAZ:00002637", "label": "Scotland",
     "synonyms": ["scottish", "scotland", "highlands"]},
    {"code": "GAZ:00002640", "label": "Wales",
     "synonyms": ["welsh", "wales", "cymru"]},
    {"code": "GAZ:00002641", "label": "England",
     "synonyms": ["english", "england"]},
    {"code": "GAZ:00001505", "label": "British Isles",
     "synonyms": ["british", "uk", "united kingdom", "britain",
                  "great britain", "british isles"]},

    # Diseases (MONDO)
    {"code": "MONDO:0004979", "label": "asthma",
     "synonyms": ["asthma", "bronchial asthma", "asthmatic", "bronchospasm"]},
    {"code": "MONDO:0005148", "label": "type 2 diabetes mellitus",
     "synonyms": ["diabetes", "type 2 diabetes", "t2d", "t2dm",
                  "diabetes mellitus type 2", "non-insulin-dependent diabetes"]},
    {"code": "MONDO:0007254", "label": "breast cancer",
     "synonyms": ["breast cancer", "breast carcinoma", "breast tumour",
                  "breast neoplasm", "mammary cancer"]},
    {"code": "MONDO:0004992", "label": "cancer",
     "synonyms": ["cancer", "carcinoma", "malignancy", "tumour",
                  "tumor", "neoplasm", "malignant neoplasm"]},
    {"code": "MONDO:0005010", "label": "autism spectrum disorder",
     "synonyms": ["autism", "asd", "autism spectrum", "autistic",
                  "pervasive developmental disorder"]},
    {"code": "MONDO:0005550", "label": "infectious disease",
     "synonyms": ["infection", "infectious disease", "infectious condition",
                  "communicable disease"]},
    {"code": "MONDO:0005015", "label": "diabetes mellitus",
     "synonyms": ["diabetes mellitus", "diabetes", "high blood sugar"]},

    # Biological sex (NCIT)
    {"code": "NCIT:C20197", "label": "male",
     "synonyms": ["male", "man", "men", "boy", "XY", "masculine"]},
    {"code": "NCIT:C16576", "label": "female",
     "synonyms": ["female", "woman", "women", "girl", "XX", "feminine"]},

    # NCIT disease codes (backwards-compatible with original 17 terms)
    {"code": "NCIT:C35553", "label": "regional failure",
     "synonyms": ["regional failure", "regional recurrence",
                  "local regional failure", "regional relapse"]},
    {"code": "NCIT:C3262",  "label": "neoplasm",
     "synonyms": ["neoplasm", "growth", "tumour", "tumor", "abnormal growth"]},
    {"code": "NCIT:C2985",  "label": "breast carcinoma",
     "synonyms": ["breast carcinoma", "breast cancer", "mammary carcinoma"]},
    {"code": "NCIT:C9305",  "label": "malignant neoplasm",
     "synonyms": ["malignant neoplasm", "malignant tumor",
                  "malignant tumour", "malignancy"]},

    # Ancestry (HANCESTRO)
    {"code": "HANCESTRO:0005", "label": "European",
     "synonyms": ["european", "white", "caucasian", "european ancestry",
                  "european descent", "western european"]},
    {"code": "HANCESTRO:0010", "label": "African",
     "synonyms": ["african", "african ancestry", "african descent",
                  "sub-saharan african", "black african"]},
    {"code": "HANCESTRO:0008", "label": "East Asian",
     "synonyms": ["east asian", "chinese", "japanese", "korean",
                  "east asian ancestry", "han chinese"]},
    {"code": "HANCESTRO:0013", "label": "South Asian",
     "synonyms": ["south asian", "indian", "bangladeshi", "pakistani",
                  "south asian ancestry", "indo-pakistani"]},
    {"code": "HANCESTRO:0006", "label": "American",
     "synonyms": ["american", "latino", "hispanic", "latin american",
                  "admixed american", "native american"]},

    # Tissue / anatomy (UBERON)
    {"code": "UBERON:0000955", "label": "brain",
     "synonyms": ["brain", "cerebral", "cerebrum", "neural tissue",
                  "cerebral cortex"]},
    {"code": "UBERON:0002048", "label": "lung",
     "synonyms": ["lung", "pulmonary", "respiratory tissue", "bronchial"]},
    {"code": "UBERON:0001264", "label": "pancreas",
     "synonyms": ["pancreas", "pancreatic", "pancreatic tissue"]},
    {"code": "UBERON:0000178", "label": "blood",
     "synonyms": ["blood", "whole blood", "peripheral blood", "blood sample"]},

    # Variant types (SO — Sequence Ontology)
    {"code": "SO:0001587", "label": "stop gained",
     "synonyms": ["stop gained", "nonsense mutation", "stop codon",
                  "premature stop", "truncating variant"]},
    {"code": "SO:0001583", "label": "missense variant",
     "synonyms": ["missense", "missense variant", "missense mutation",
                  "amino acid change", "nonsynonymous"]},
    {"code": "SO:0001819", "label": "synonymous variant",
     "synonyms": ["synonymous", "synonymous variant", "silent mutation",
                  "synonymous mutation", "silent variant"]},
]


def _load_extra_terms_from_csv(csv_path: str) -> list[dict]:
    """
    Import additional ontology terms from a sBeacon-style terms.csv file.

    Expected CSV format (flexible — handles various sBeacon exports):
        id,label
        MONDO:0004979,asthma
        GAZ:00002638,Northern Ireland
        ...

    Returns a list of dicts with keys: code, label, synonyms (empty list).
    Skips any rows that duplicate codes already in ONTOLOGY_TERMS.
    """
    existing_codes = {t["code"] for t in ONTOLOGY_TERMS}
    extra: list[dict] = []

    with open(csv_path, newline="", encoding="utf-8") as f:
        # Detect delimiter (comma or tab)
        sample = f.read(2048)
        f.seek(0)
        delimiter = "\t" if "\t" in sample else ","
        reader = csv.DictReader(f, delimiter=delimiter)

        for row in reader:
            # Handle different column name conventions
            code  = (row.get("id") or row.get("code") or row.get("ID") or "").strip()
            label = (row.get("label") or row.get("Label") or row.get("term") or "").strip()
            if not code or not label:
                continue
            if code in existing_codes:
                continue
            extra.append({"code": code, "label": label, "synonyms": []})
            existing_codes.add(code)

    print(f"  Imported {len(extra)} new terms from {csv_path}")
    return extra


def build(extra_csv: str | None = None) -> None:
    """
    Build (or rebuild) the FAISS index and ontology_meta.json.

    Args:
        extra_csv: Optional path to a sBeacon terms.csv file with additional terms.
    """
    try:
        import faiss
        from sentence_transformers import SentenceTransformer
    except ImportError:
        print("Missing packages. Run: pip install faiss-cpu sentence-transformers")
        sys.exit(1)

    index_path = Path(__file__).resolve().parent / "ontology.index"
    meta_path  = Path(__file__).resolve().parent / "ontology_meta.json"

    # Merge base terms + any extra terms from CSV
    all_terms = list(ONTOLOGY_TERMS)
    if extra_csv:
        print(f"Importing extra terms from: {extra_csv}")
        all_terms += _load_extra_terms_from_csv(extra_csv)

    print(f"Loading embedding model (all-MiniLM-L6-v2)...")
    model = SentenceTransformer("all-MiniLM-L6-v2")

    # One vector entry per text variation (label + all synonyms)
    all_texts: list[str] = []
    meta:      list[dict] = []
    for term in all_terms:
        texts = [term["label"]] + term.get("synonyms", [])
        for t in texts:
            all_texts.append(t.lower())   # lowercase for consistent matching
            meta.append({"code": term["code"], "label": term["label"]})

    print(f"Encoding {len(all_texts)} text entries ({len(all_terms)} terms + synonyms)...")
    embeddings = model.encode(
        all_texts,
        normalize_embeddings=True,
        show_progress_bar=True,
        batch_size=64,
    )
    embeddings = np.array(embeddings, dtype="float32")

    # Inner product on L2-normalised vectors == cosine similarity
    dim   = embeddings.shape[1]
    index = faiss.IndexFlatIP(dim)
    index.add(embeddings)

    faiss.write_index(index, str(index_path))
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)

    print(f"\n✅  FAISS index built successfully")
    print(f"    Terms:   {len(all_terms)}")
    print(f"    Vectors: {len(all_texts)}")
    print(f"    Saved:   {index_path}")
    print(f"    Saved:   {meta_path}")

    # Smoke test
    print("\nSmoke test:")
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    # Reload module with fresh cache
    import importlib
    import ontology.ontology_lookup as ol_mod
    ol_mod._cache = None
    from ontology.ontology_lookup import lookup
    for test in ["Northern Ireland", "asthma", "male", "breast cancer", "European"]:
        r = lookup(test, top_k=1)
        if r:
            print(f"  '{test}' → {r[0].code} ({r[0].label}) [{r[0].similarity:.4f}]")
        else:
            print(f"  '{test}' → no match (check similarity threshold)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Build or rebuild the FAISS ontology index."
    )
    parser.add_argument(
        "--import", dest="csv_path", default=None,
        metavar="PATH",
        help="Path to a sBeacon terms.csv file to import additional ontology terms.",
    )
    args = parser.parse_args()
    build(extra_csv=args.csv_path)

"""
agents/joiner_agent.py
-----------------------
Agent 3 — Data Joiner.

Takes outputs from Agent 1 (VCF) and Agent 2 (Beacon) and merges them into
a single unified table that links:
  - Genomic variants (from VCF agent CSV)
  - Patient/sample filters (from Beacon agent JSON)
  - Shared metadata (chromosome, position, ontology codes)

Output: a unified CSV and a plain English summary saved to outputs/.

How it works:
  1. LOAD    — reads VCF CSV and Beacon JSON from outputs/ (or from provided paths)
  2. ENRICH  — asks Ollama to describe the context of each variant using the
               Beacon filters (e.g. "these variants were found while querying
               for male individuals with regional failure")
  3. JOIN    — merges the two datasets on shared fields (chromosome, position)
               where available; otherwise annotates VCF rows with Beacon context
  4. SAVE    — writes unified CSV + plain English summary to outputs/
"""

import csv
import glob
import json
import re
import sys
from datetime import datetime
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config.settings import OLLAMA_BASE_URL, OLLAMA_MODEL, OUTPUTS_DIR

OUTPUTS_DIR.mkdir(exist_ok=True)


def _ollama(prompt: str, system: str = "") -> str:
    """Send a prompt to local Ollama, return response text."""
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "system": system,
        "stream": False,
        "options": {"temperature": 0.0},
    }
    resp = requests.post(
        f"{OLLAMA_BASE_URL}/api/generate",
        json=payload,
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["response"].strip()


def _find_latest_output(pattern: str) -> Path | None:
    """Find the most recently created file matching a glob pattern in outputs/."""
    matches = sorted(
        OUTPUTS_DIR.glob(pattern),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return matches[0] if matches else None


def _load_vcf_csv(path: Path) -> list[dict]:
    """
    Load a VCF agent CSV output.
    Returns list of row dicts. Handles both full VCF CSVs and cleaned outputs.
    """
    rows: list[dict] = []
    try:
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Normalise column names (VCF headers vary)
                normalised = {}
                for k, v in row.items():
                    key = k.lstrip("#").strip().upper()
                    normalised[key] = v.strip() if v else ""
                rows.append(normalised)
    except Exception as e:
        raise ValueError(f"Could not read VCF CSV at {path}: {e}")
    return rows


def _load_beacon_json(path: Path) -> dict:
    """
    Load a Beacon agent JSON output.
    Accepts both the raw query JSON and the full saved .txt file.
    """
    try:
        text = path.read_text(encoding="utf-8")
        # If it's a .txt file, extract the JSON block
        json_match = re.search(r"\{.*\}", text, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
    except Exception as e:
        raise ValueError(f"Could not read Beacon JSON at {path}: {e}")
    return {}


def _extract_beacon_context(beacon_data: dict) -> dict:
    """
    Pull the key fields from the Beacon query for use in enrichment.
    Returns a dict with: scope, granularity, filters (list of label strings),
    variant_query (if present).
    """
    params = beacon_data.get("query", {}).get("requestParameters", {})
    filters = params.get("filters", [])
    filter_labels = [f.get("label", f.get("id", "")) for f in filters]
    filter_codes = [f.get("id", "") for f in filters]

    return {
        "scope": params.get("scope", "individuals"),
        "granularity": params.get("granularity", "record"),
        "filter_labels": filter_labels,
        "filter_codes": filter_codes,
        "filter_summary": ", ".join(filter_labels) if filter_labels else "no filters",
        "variant_query": params.get("variantQuery", {}),
    }


def _enrich_with_ollama(vcf_rows: list[dict], beacon_ctx: dict) -> str:
    """
    Ask Ollama to describe the combined dataset in plain English.
    Gives the analyst context about what the two agents found together.
    """
    vcf_summary = f"{len(vcf_rows)} variant(s)"
    if vcf_rows:
        sample_row = vcf_rows[0]
        chrom = sample_row.get("CHROM", sample_row.get("chrom", "?"))
        pos = sample_row.get("POS", sample_row.get("pos", "?"))
        vcf_summary += f" on chromosome {chrom} around position {pos}"

    system = (
        "You are a bioinformatics analyst. Write a 2–3 sentence summary "
        "describing the combined result of a VCF query and a Beacon query. "
        "Be concise and factual."
    )
    prompt = (
        f"VCF query returned: {vcf_summary}\n"
        f"Beacon query was for: scope={beacon_ctx['scope']}, "
        f"granularity={beacon_ctx['granularity']}, "
        f"filters=[{beacon_ctx['filter_summary']}]\n\n"
        f"Write a 2–3 sentence plain English summary of what was found "
        f"and what the combined dataset represents:"
    )
    return _ollama(prompt, system)


def _join_datasets(
    vcf_rows: list[dict],
    beacon_ctx: dict,
) -> list[dict]:
    """
    Merge VCF variant rows with Beacon query context.

    Join strategy:
    - If the Beacon query included chromosome/position coordinates that overlap
      with the VCF output, mark matching rows as "overlap=True".
    - All VCF rows are annotated with the Beacon filter context regardless.

    Returns a list of enriched row dicts ready for CSV output.
    """
    variant_query = beacon_ctx.get("variant_query", {})
    beacon_chrom = str(variant_query.get("referenceName", "")).upper()
    beacon_start = variant_query.get("start")
    beacon_end = variant_query.get("end")

    joined: list[dict] = []
    for row in vcf_rows:
        enriched = dict(row)

        # Annotate with Beacon context
        enriched["beacon_scope"] = beacon_ctx["scope"]
        enriched["beacon_granularity"] = beacon_ctx["granularity"]
        enriched["beacon_filters"] = "; ".join(beacon_ctx["filter_codes"])
        enriched["beacon_filter_labels"] = "; ".join(beacon_ctx["filter_labels"])

        # Check positional overlap
        overlap = False
        if beacon_chrom and beacon_start is not None and beacon_end is not None:
            row_chrom = str(row.get("CHROM", row.get("chrom", ""))).upper().lstrip("CHR")
            bc_chrom = beacon_chrom.lstrip("CHR")
            try:
                row_pos = int(row.get("POS", row.get("pos", 0)) or 0)
                if row_chrom == bc_chrom and beacon_start <= row_pos <= beacon_end:
                    overlap = True
            except (ValueError, TypeError):
                pass
        enriched["beacon_position_overlap"] = "yes" if overlap else "no"

        joined.append(enriched)

    return joined


def _save_joined(
    joined_rows: list[dict],
    summary: str,
    vcf_path: Path,
    beacon_path: Path,
    timestamp: str,
) -> tuple[Path, Path]:
    """Save the joined dataset as .txt summary + .csv data file."""
    base = f"{timestamp}_joined"

    # .txt — summary record
    txt_path = OUTPUTS_DIR / f"{base}.txt"
    txt_path.write_text(
        f"Joined Output\n"
        f"{'─' * 60}\n"
        f"VCF source:    {vcf_path.name}\n"
        f"Beacon source: {beacon_path.name}\n"
        f"Rows joined:   {len(joined_rows)}\n"
        f"Time:          {timestamp}\n"
        f"{'─' * 60}\n\n"
        f"SUMMARY:\n{summary}\n"
    )

    # .csv — unified data
    csv_path = OUTPUTS_DIR / f"{base}.csv"
    if joined_rows:
        fieldnames = list(joined_rows[0].keys())
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(joined_rows)
    else:
        csv_path.write_text("No rows to write.\n")

    return txt_path, csv_path


def run_joiner(
    vcf_csv_path: str | Path | None = None,
    beacon_json_path: str | Path | None = None,
    verbose: bool = True,
) -> dict:
    """
    Join VCF agent output and Beacon agent output into a unified table.

    Args:
        vcf_csv_path:     Path to a VCF agent .csv output file.
                          If None, auto-detects the most recent .csv in outputs/.
        beacon_json_path: Path to a Beacon agent .txt or .json output file.
                          If None, auto-detects the most recent beacon .txt in outputs/.
        verbose:          Print progress to stdout.

    Returns:
        Dict with keys: summary, csv_path, txt_path, row_count.
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    if verbose:
        print("\nJoiner Agent")
        print("─" * 50)

    # LOAD: Resolve input files
    if vcf_csv_path is None:
        vcf_file = _find_latest_output("*_vcf*.csv")
        if vcf_file is None:
            vcf_file = _find_latest_output("*.csv")
        if vcf_file is None:
            raise FileNotFoundError(
                "No VCF CSV found in outputs/. "
                "Run: python main.py -a vcf -q '...' first."
            )
    else:
        vcf_file = Path(vcf_csv_path)

    if beacon_json_path is None:
        beacon_file = _find_latest_output("*beacon*.txt")
        if beacon_file is None:
            beacon_file = _find_latest_output("*beacon*.json")
        if beacon_file is None:
            raise FileNotFoundError(
                "No Beacon output found in outputs/. "
                "Run: python main.py -a beacon -q '...' first."
            )
    else:
        beacon_file = Path(beacon_json_path)

    if verbose:
        print(f"VCF CSV:     {vcf_file.name}")
        print(f"Beacon file: {beacon_file.name}")

    vcf_rows = _load_vcf_csv(vcf_file)
    beacon_data = _load_beacon_json(beacon_file)

    if verbose:
        print(f"   Loaded {len(vcf_rows)} VCF rows")
        filters = beacon_data.get("query", {}).get("requestParameters", {}).get("filters", [])
        print(f"   Loaded Beacon query with {len(filters)} filter(s)")

    # ENRICH: Generate summary with Ollama
    beacon_ctx = _extract_beacon_context(beacon_data)

    if verbose:
        print("\nGenerating enrichment summary...", end=" ", flush=True)
    summary = _enrich_with_ollama(vcf_rows, beacon_ctx)
    if verbose:
        print("done")

    # JOIN: Annotate VCF rows with Beacon context
    if verbose:
        print("Joining datasets...", end=" ", flush=True)
    joined = _join_datasets(vcf_rows, beacon_ctx)
    if verbose:
        print(f"done — {len(joined)} rows")

    # SAVE: Write output files
    txt_path, csv_path = _save_joined(joined, summary, vcf_file, beacon_file, timestamp)

    if verbose:
        print(f"Saved: {txt_path.name}")
        print(f"CSV:   {csv_path.name}")
        print("─" * 50)
        print(f"\nSummary: {summary}")

    return {
        "summary": summary,
        "csv_path": str(csv_path),
        "txt_path": str(txt_path),
        "row_count": len(joined),
        "beacon_context": beacon_ctx,
    }


if __name__ == "__main__":
    result = run_joiner()
    print(f"\nJoined {result['row_count']} rows -> {result['csv_path']}")
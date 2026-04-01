"""
agents/beacon_agent.py
----------------------
Agent 2 — Beacon Query Builder.
Scope -> Granularity -> Keywords -> Ontology -> Coordinates -> JSON -> Save
Now also sends the query to a live Beacon endpoint if configured.
"""

import csv
import json
import re
import sys
from datetime import datetime
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config.settings import BEACON_BASE_URL, OLLAMA_BASE_URL, OLLAMA_MODEL, OUTPUTS_DIR
from ontology.ontology_lookup import lookup

OUTPUTS_DIR.mkdir(exist_ok=True)

# Mapping of Beacon scope to endpoint path
_SCOPE_TO_ENDPOINT = {
    "individuals": "/individuals",
    "variants":    "/g_variants",
    "biosamples":  "/biosamples",
    "cohorts":     "/cohorts",
}


def _ollama(prompt: str, system: str = "") -> str:
    """Send a prompt to Ollama and return the response."""
    resp = requests.post(
        f"{OLLAMA_BASE_URL}/api/generate",
        json={
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "system": system,
            "stream": False,
            "options": {"temperature": 0.0}
        },
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["response"].strip()


def _detect_scope_and_granularity(query: str) -> tuple[str, str]:
    """Use the LLM to decide the Beacon scope and granularity."""
    system = (
        "You are a Beacon v2 API expert. Reply with ONLY a JSON object.\n"
        "scope: individuals|variants|biosamples|cohorts\n"
        "granularity: record|count|boolean\n"
        "- record: find/get/show/list (DEFAULT)\n"
        "- count: ONLY for 'how many'/'count'/'number of'\n"
        "- boolean: ONLY for 'do any exist'/'is there'/'yes or no'\n"
    )
    prompt = f'Classify: "{query}"\nReply: {{"scope":"...","granularity":"..."}}'
    raw = _ollama(prompt, system)
    try:
        m = re.search(r"\{[^}]+\}", raw)
        if m:
            data = json.loads(m.group())
            scope = data.get("scope", "individuals")
            gran = data.get("granularity", "record")
            if scope not in ("individuals", "variants", "biosamples", "cohorts"):
                scope = "individuals"
            if gran not in ("record", "count", "boolean"):
                gran = "record"
            return scope, gran
    except Exception:
        pass
    return "individuals", "record"


def _extract_keywords(query: str) -> list[str]:
    """Extract biomedical filter terms from the query."""
    system = (
        "Extract biomedical filter terms. Reply ONLY with a JSON array of strings.\n"
        "Include: diseases, sex, ancestry, tissue types, geographic locations.\n"
        "Exclude: chromosome names, position numbers, 'first','from','to','base'.\n"
        "Examples:\n"
        "'male individuals with regional failure' -> [\"male\",\"regional failure\"]\n"
        "'individuals from Northern Ireland with asthma' -> [\"Northern Ireland\",\"asthma\"]\n"
        "'variants on chromosome 2' -> []\n"
    )
    prompt = f'Extract from: "{query}"\nJSON array only:'
    raw = _ollama(prompt, system)
    try:
        m = re.search(r"\[.*?\]", raw, re.DOTALL)
        if m:
            return [kw for kw in json.loads(m.group()) if isinstance(kw, str) and kw.strip()]
    except Exception:
        pass
    return []


def _extract_variant_coords(query: str) -> dict | None:
    """Extract variant coordinates (referenceName, start, end) from query."""
    chrom_match = re.search(r"chr(?:omosome)?\s*(\w+)", query, re.IGNORECASE)
    if not chrom_match:
        return None
    chrom = chrom_match.group(1).upper().lstrip("0") or "1"
    variant: dict = {"referenceName": chrom}

    def parse_pos(s: str) -> int:
        s = s.replace(",", "").strip()
        if s.upper().endswith("M"):
            return int(float(s[:-1]) * 1_000_000)
        return int(float(s))

    pos_match = re.search(
        r"([\d,]+(?:\.\d+)?[mM]?)\s*(?:to|-)\s*([\d,]+(?:\.\d+)?[mM]?)", query)
    if pos_match:
        try:
            variant["start"] = parse_pos(pos_match.group(1))
            variant["end"] = parse_pos(pos_match.group(2))
        except ValueError:
            pass
    return variant


def _save_outputs(query: str, result: dict, timestamp: str) -> tuple[Path, Path]:
    """Save the Beacon query JSON and a CSV summary."""
    safe_q = re.sub(r"[^\w\s-]", "", query)[:40].strip().replace(" ", "_")
    base_name = f"{timestamp}_beacon_{safe_q}"
    txt_path = OUTPUTS_DIR / f"{base_name}.txt"
    txt_path.write_text(
        f"Query:    {query}\nTime:     {timestamp}\n{'─'*60}\n\n"
        f"BEACON v2 QUERY:\n{json.dumps(result, indent=2)}\n"
    )
    params = result.get("query", {}).get("requestParameters", {})
    filters = params.get("filters", [])
    csv_path = OUTPUTS_DIR / f"{base_name}.csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["query", "scope", "granularity", "filter_id", "filter_label"])
        if filters:
            for fi in filters:
                writer.writerow([query, params.get("scope", ""),
                                 params.get("granularity", ""),
                                 fi.get("id", ""), fi.get("label", "")])
        else:
            writer.writerow([query, params.get("scope", ""),
                             params.get("granularity", ""), "", ""])
    return txt_path, csv_path


def run_beacon_query(user_query: str, verbose: bool = True) -> dict:
    """
    Build a valid Beacon v2 JSON query from plain English.
    Optionally sends to live Beacon endpoint (if BEACON_BASE_URL is set).
    Saves to outputs/ as .txt and .csv.

    Args:
        user_query: The user's natural language question.
        verbose: Print progress messages.

    Returns:
        A dictionary containing the Beacon query and optional response.
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if verbose:
        print(f"\nQuery: {user_query}\n{'─'*50}")

    if verbose:
        print("Detecting scope and granularity...", end=" ", flush=True)
    scope, granularity = _detect_scope_and_granularity(user_query)
    endpoint = _SCOPE_TO_ENDPOINT.get(scope, "/individuals")
    if verbose:
        print(f"scope={scope}, granularity={granularity}")
        print(f"   -> endpoint: {BEACON_BASE_URL}{endpoint}")

    if verbose:
        print("Extracting filter keywords...", end=" ", flush=True)
    keywords = _extract_keywords(user_query)
    if verbose:
        print(f"{keywords}")

    filters: list[dict] = []
    if keywords:
        if verbose:
            print("Looking up ontology codes...")
        for kw in keywords:
            matches = lookup(kw, top_k=1)
            if matches:
                best = matches[0]
                if verbose:
                    print(f"   '{kw}' -> {best.code} ({best.label}) [{best.similarity:.4f}]")
                filters.append({"id": best.code, "label": best.label, "operator": "="})
            else:
                if verbose:
                    print(f"   '{kw}' -> no match (similarity < 0.5), skipping")

    variant_coords = _extract_variant_coords(user_query)
    if verbose and variant_coords:
        print(f"Variant coords: {variant_coords}")

    request_params: dict = {"scope": scope, "granularity": granularity}
    if filters:
        request_params["filters"] = filters
    if variant_coords:
        request_params["variantQuery"] = variant_coords

    result = {
        "meta": {"apiVersion": "v2.0"},
        "query": {"requestParameters": request_params},
    }

    # Send to live Beacon endpoint if base URL is not empty
    if BEACON_BASE_URL:
        try:
            resp = requests.post(
                f"{BEACON_BASE_URL}{endpoint}",
                headers={"Content-Type": "application/json"},
                json=result, timeout=30,
            )
            resp.raise_for_status()
            result["beacon_response"] = resp.json()
        except Exception as e:
            result["beacon_response"] = {"error": str(e)}
            if verbose:
                print(f"Beacon endpoint unreachable: {e}")

    txt_path, csv_path = _save_outputs(user_query, result, timestamp)
    if verbose:
        print(f"{'─'*50}\nQuery built\n{txt_path.name}\n{csv_path.name}\n")
    return result


if __name__ == "__main__":
    for q in [
        "Find male individuals with regional failure",
        "How many individuals are from Northern Ireland?",
        "Do any Europeans with breast cancer exist?",
    ]:
        print(json.dumps(run_beacon_query(q), indent=2))
        print()
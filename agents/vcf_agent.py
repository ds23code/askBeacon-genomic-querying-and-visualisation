"""
agents/vcf_agent.py
-------------------
Agent 1 — VCF Extractor.
ReAct loop: Plan -> Act -> Observe -> Reflect -> Summarise.

Improvements:
- Better coordinate extraction (handles "between X and Y", "X to Y", "X-Y").
- If coordinates are given, uses them; otherwise fetches a sample.
"""

import csv
import io
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config.settings import (
    DEFAULT_VCF_FILE, GENOMES_S3_BASE, OLLAMA_BASE_URL,
    OLLAMA_MODEL, OUTPUTS_DIR, TEMPLATES_DIR,
)

# Load the bcftools command templates
_template_text = (TEMPLATES_DIR / "bcftools_template.md").read_text()

# 1000 Genomes chromosome -> S3 URL map
_1KG_FILES: dict[str, str] = {
    str(i): GENOMES_S3_BASE.format(chrom=i) for i in range(1, 23)
}
_1KG_FILES["X"] = (
    "s3://1000genomes/release/20130502/"
    "ALL.chrX.phase3_shapeit2_mvncall_integrated_v5a.20130502.genotypes.vcf.gz"
)
_1KG_FILES["Y"] = (
    "s3://1000genomes/release/20130502/"
    "ALL.chrY.phase3_integrated_v2a.20130502.genotypes.vcf.gz"
)

_ORDINALS: dict[str, str] = {
    "first": "1", "second": "2", "third": "3", "fourth": "4", "fifth": "5",
    "sixth": "6", "seventh": "7", "eighth": "8", "ninth": "9", "tenth": "10",
    "eleventh": "11", "twelfth": "12", "thirteenth": "13", "fourteenth": "14",
    "fifteenth": "15", "sixteenth": "16", "seventeenth": "17", "eighteenth": "18",
    "nineteenth": "19", "twentieth": "20", "twenty-first": "21", "twenty-second": "22",
}

MAX_ATTEMPTS = 3
OUTPUTS_DIR.mkdir(exist_ok=True)

# Forbidden shell tokens for security
_FORBIDDEN = [";", "&&", "||", "`", "$(", "rm ", "mv ", "dd ", ">"]


def _detect_chromosome(query: str) -> str | None:
    """Extract chromosome number from the query using various patterns."""
    q = query.lower()
    for word, num in _ORDINALS.items():
        if word in q and "chrom" in q:
            return num
    m = re.search(r"chr(?:omosome)?\s*(\w+)", q)
    if m:
        return m.group(1).upper().lstrip("0") or "1"
    m = re.search(r"chrom\w*\s+(\d+)", q)
    if m:
        return m.group(1)
    return None


def _resolve_vcf_file(query: str, vcf_file: str | None) -> str:
    """Determine the VCF file path based on query and optional override."""
    if vcf_file:
        return vcf_file
    chrom = _detect_chromosome(query)
    if chrom and chrom in _1KG_FILES:
        return _1KG_FILES[chrom]
    return DEFAULT_VCF_FILE


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


def _extract_command(raw: str) -> str:
    """Extract a bcftools command from the LLM's response."""
    cmd = ""
    for line in raw.splitlines():
        line = line.strip().strip("`")
        if line.startswith("bcftools"):
            cmd = line
            break
    else:
        m = re.search(r"bcftools\s+\S+.*", raw)
        cmd = m.group().strip("`").strip() if m else raw.splitlines()[0].strip()
    # Strip output redirection flags
    cmd = re.sub(r"\s+-Oz\b", "", cmd)
    cmd = re.sub(r"\s+-o\s+\S+", "", cmd)
    cmd = re.sub(r"\s+--output(?:=\S+|\s+\S+)", "", cmd)
    return cmd.strip()


def _fix_region_format(cmd: str) -> str:
    """Remove 'chr' prefix from --regions argument."""
    match = re.search(r"--regions\s+([^\s]+)", cmd)
    if match:
        region_arg = match.group(1)
        if region_arg.startswith("chr"):
            fixed = region_arg[3:]
            cmd = cmd.replace(f"--regions {region_arg}", f"--regions {fixed}")
    return cmd


def _parse_coordinate(s: str) -> int:
    """Convert a string like '5.5M' to integer base pairs."""
    s = s.replace(",", "").strip()
    if s.upper().endswith("M"):
        return int(float(s[:-1]) * 1_000_000)
    if s.upper().endswith("K"):
        return int(float(s[:-1]) * 1_000)
    return int(float(s))


def _extract_coords(query: str) -> tuple[str | None, int | None, int | None]:
    """
    Extract chromosome, start, end from a query.

    Handles patterns:
      - "chr2:5500000-5510000"
      - "chromosome 2 from 5.5M to 5.51M"
      - "between 5.5M and 5.51M on chr2"
    """
    # First, detect chromosome
    chrom_match = re.search(r"chr(?:omosome)?\s*(\w+)", query, re.IGNORECASE)
    chrom = chrom_match.group(1).upper() if chrom_match else None
    if not chrom:
        return None, None, None

    # Look for two numbers (possibly with M/k) separated by "to", "-", or "between ... and ..."
    patterns = [
        r"([\d,]+(?:\.\d+)?[mMkK]?)\s*(?:to|-)\s*([\d,]+(?:\.\d+)?[mMkK]?)",  # "5.5M to 5.51M"
        r"between\s+([\d,]+(?:\.\d+)?[mMkK]?)\s+and\s+([\d,]+(?:\.\d+)?[mMkK]?)",  # "between 5.5M and 5.51M"
        r"from\s+([\d,]+(?:\.\d+)?[mMkK]?)\s+to\s+([\d,]+(?:\.\d+)?[mMkK]?)",  # "from 5.5M to 5.51M"
    ]
    for pattern in patterns:
        m = re.search(pattern, query, re.IGNORECASE)
        if m:
            try:
                start = _parse_coordinate(m.group(1))
                end = _parse_coordinate(m.group(2))
                return chrom, start, end
            except (ValueError, TypeError):
                pass

    # If we get here, only a chromosome was mentioned, no coordinates
    return chrom, None, None


def _get_vcf_context(vcf_file: str) -> str:
    """Read VCF header for context (metadata only)."""
    try:
        result = subprocess.run(
            f"bcftools view -h {vcf_file} 2>/dev/null | head -30",
            shell=True, capture_output=True, text=True, timeout=30,
        )
        header = result.stdout.strip()
        if not header:
            return "Header not available."
        contigs = re.findall(r"##contig=<ID=([^,>]+)", header)[:5]
        info_fields = re.findall(r"##INFO=<ID=([^,]+)", header)[:10]
        format_fields = re.findall(r"##FORMAT=<ID=([^,]+)", header)[:5]
        reference = re.findall(r"##reference=(.+)", header)
        parts = []
        if contigs:
            parts.append(f"Chromosomes: {', '.join(contigs)}")
        if info_fields:
            parts.append(f"INFO fields: {', '.join(info_fields)}")
        if format_fields:
            parts.append(f"FORMAT fields: {', '.join(format_fields)}")
        if reference:
            parts.append(f"Reference: {reference[0].strip()}")
        return "\n".join(parts) if parts else "Standard VCF file."
    except Exception:
        return "Header not available."


def _generate_command(query: str, vcf_file: str, vcf_context: str,
                      previous_attempts: list[tuple[str, str]],
                      has_coords: bool) -> str:
    """Generate a bcftools command using the LLM."""
    history = ""
    if previous_attempts:
        history = "\nPREVIOUS FAILED ATTEMPTS (do NOT repeat):\n"
        for i, (cmd, err) in enumerate(previous_attempts, 1):
            history += f"  Attempt {i}: {cmd}\n  Error: {err}\n"

    system = (
        "You are a bioinformatics expert. Generate a single bcftools command.\n"
        "STRICT RULES:\n"
        "- Output ONLY the command, nothing else\n"
        "- Must start with 'bcftools'\n"
        "- Use the EXACT VCF file path provided\n"
        "- NEVER add -Oz, -o, --output flags\n"
        "- In --regions flag NEVER use 'chr' prefix. Use '2:5500000-5510000' NOT 'chr2:5500000-5510000'\n"
        "- Output must go to stdout only\n"
        f"- The user {'did' if has_coords else 'did NOT'} specify a genomic region. "
        f"{'Include --regions with the coordinates' if has_coords else 'Omit the --regions flag entirely'}.\n"
        "- Use these templates as reference:\n\n"
        + _template_text
    )
    prompt = (
        f"VCF file: {vcf_file}\n"
        f"File contents summary:\n{vcf_context}\n"
        f"User query: \"{query}\"\n"
        f"{history}"
        f"Output the bcftools command only:"
    )
    cmd = _extract_command(_ollama(prompt, system))
    cmd = _fix_region_format(cmd)
    # If coordinates were not given, remove any --regions flag that might have been added.
    if not has_coords:
        cmd = re.sub(r"--regions\s+\S+", "", cmd)
    return cmd


def _run_command(command: str) -> tuple[str, str, bool]:
    """Execute bcftools command safely. Returns (stdout, stderr, success)."""
    if not command.startswith("bcftools"):
        return "", f"Rejected: must start with bcftools. Got: {command!r}", False
    for token in _FORBIDDEN:
        if token in command:
            return "", f"Rejected: forbidden token '{token}'", False
    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            return "", result.stderr.strip() or f"Exit code {result.returncode}", False
        return result.stdout, "", True
    except subprocess.TimeoutExpired:
        return "", "Timed out after 120 seconds.", False
    except Exception as e:
        return "", str(e), False


def _clean_vcf_output(raw: str) -> str:
    """Keep first 5 meta lines, keep only first 9 columns for data rows."""
    meta: list[str] = []
    data: list[str] = []
    meta_count = 0
    for line in raw.splitlines():
        if line.startswith("##"):
            if meta_count < 5:
                meta.append(line)
                meta_count += 1
        elif line.startswith("#"):
            # Keep only first 9 columns for the header
            cols = line.split("\t")[:9]
            meta.append("\t".join(cols))
        else:
            # Data rows: keep only first 9 columns
            cols = line.split("\t")[:9]
            data.append("\t".join(cols))
    return "\n".join(meta + data)


def _is_useful_output(cleaned: str) -> tuple[bool, str]:
    """Check if cleaned output contains actual variant data rows."""
    if not cleaned or cleaned == "(no output)":
        return False, "Empty output"
    data_rows = [l for l in cleaned.splitlines() if l.strip() and not l.startswith("#")]
    if not data_rows:
        return False, "Only header lines — no variant data rows"
    return True, f"Found {len(data_rows)} data row(s)"


def _summarise(query: str, command: str, truncated_cleaned: str) -> str:
    """Ask Ollama to summarise the VCF result in plain English."""
    data_lines = [l for l in truncated_cleaned.splitlines() if l and not l.startswith("#")]
    system = (
        "You are a bioinformatics assistant. Summarise the result in 2-3 plain English "
        "sentences. Be specific about counts, positions, variant types. Don't repeat the command."
    )
    prompt = (
        f'User asked: "{query}"\n'
        f"Command: {command}\n"
        f"Rows returned: {len(data_lines)}\n"
        f"First lines:\n{truncated_cleaned[:500]}\n\nSummarise:"
    )
    return _ollama(prompt, system)


def _vcf_to_csv(cleaned: str) -> str | None:
    """Convert the cleaned VCF output (with header) to CSV format."""
    headers: list[str] | None = None
    rows: list[list[str]] = []
    for line in cleaned.splitlines():
        if line.startswith("##"):
            continue
        elif line.startswith("#"):
            headers = line.lstrip("#").split("\t")
        elif line.strip() and headers:
            rows.append(line.split("\t"))
    if not headers or not rows:
        return None
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(headers)
    writer.writerows(rows)
    return buf.getvalue()


def _save_outputs(query: str, command: str, raw_output: str, cleaned_output: str,
                  summary: str, attempts: int, timestamp: str) -> tuple[Path, Path | None]:
    """Save the VCF results to files."""
    safe_q = re.sub(r"[^\w\s-]", "", query)[:50].strip().replace(" ", "_")
    base_name = f"{timestamp}_{safe_q}_vcf"
    txt_path = OUTPUTS_DIR / f"{base_name}.txt"
    txt_path.write_text(
        f"Query:    {query}\n"
        f"Command:  {command}\n"
        f"Attempts: {attempts}\n"
        f"Time:     {timestamp}\n"
        f"{'─' * 60}\n\n"
        f"SUMMARY:\n{summary}\n\n"
        f"{'─' * 60}\n\n"
        f"FULL RAW OUTPUT (bcftools stdout):\n{raw_output}"
    )
    csv_data = _vcf_to_csv(cleaned_output)
    csv_path: Path | None = None
    if csv_data:
        csv_path = OUTPUTS_DIR / f"{base_name}.csv"
        csv_path.write_text(csv_data)
    return txt_path, csv_path


def _get_sample_variants(vcf_file: str, max_lines: int = 100) -> str:
    """Fetch first max_lines variant lines from the VCF (excluding header)."""
    try:
        result = subprocess.run(
            f"bcftools view -H {vcf_file} | head -{max_lines}",
            shell=True, capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0:
            return ""
        return result.stdout
    except Exception:
        return ""


def run_vcf_query(user_query: str, vcf_file: str | None = None,
                  verbose: bool = True) -> str:
    """
    Run the VCF ReAct loop. If no coordinates are provided, fetch a sample.

    Args:
        user_query: The user's natural language question.
        vcf_file: Optional explicit VCF file path.
        verbose: Print progress messages.

    Returns:
        A string containing the final summary and raw output (or error).
    """
    vcf = _resolve_vcf_file(user_query, vcf_file)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    chrom, start, end = _extract_coords(user_query)
    has_coords = chrom is not None and start is not None and end is not None

    if verbose:
        print(f"\nQuery: {user_query}")
        print(f"File:  {vcf}")
        print("─" * 50)

    if not has_coords:
        # No coordinates – just return a sample
        if verbose:
            print("No coordinates specified, fetching a sample of variants...")
        sample_raw = _get_sample_variants(vcf, max_lines=100)
        if not sample_raw:
            return "No variants found in the sample."
        cleaned = _clean_vcf_output(sample_raw)
        command = f"bcftools view -H {vcf} | head -100"
        summary = f"Showing a sample of {len(cleaned.splitlines())} variant lines from chromosome {chrom} (first 100 rows)."
        txt_path, csv_path = _save_outputs(
            user_query, command, sample_raw, cleaned,
            summary, 1, timestamp,
        )
        if verbose:
            print(f"Saved: {txt_path.name}")
            if csv_path:
                print(f"CSV:   {csv_path.name}")
            print("─" * 50)
            print(f"\nSummary: {summary}")
        return (
            f"Query:    {user_query}\n"
            f"Command:  {command}\n"
            f"Attempts: 1\n"
            f"Time:     {timestamp}\n"
            f"{'─' * 60}\n\n"
            f"SUMMARY:\n{summary}\n\n"
            f"{'─' * 60}\n\n"
            f"RAW OUTPUT (sample):\n{cleaned[:8000]}"
        )

    # Coordinates present – proceed with ReAct loop
    if verbose:
        print(f"Coordinates: {chrom}:{start}-{end}")
        print("Reading VCF header for context...", end=" ", flush=True)
    vcf_context = _get_vcf_context(vcf)
    if verbose:
        print("done")

    previous_attempts: list[tuple[str, str]] = []
    final_raw = ""
    final_cleaned = ""
    final_command = ""

    for attempt in range(1, MAX_ATTEMPTS + 1):
        if verbose:
            print(f"\nAttempt {attempt}/{MAX_ATTEMPTS} — generating command...", end=" ", flush=True)
        command = _generate_command(user_query, vcf, vcf_context, previous_attempts, has_coords)
        if verbose:
            print(f"\n   $ {command}")
        if verbose:
            print("Running...", end=" ", flush=True)
        raw_output, error, success = _run_command(command)
        if verbose:
            print("done")
        if not success:
            if verbose:
                print(f"   Failed: {error[:120]}")
            previous_attempts.append((command, error))
            continue

        cleaned = _clean_vcf_output(raw_output)
        useful, reason = _is_useful_output(cleaned)
        if verbose:
            print(f"   Observe: {reason}")
        if useful:
            final_raw = raw_output
            final_cleaned = cleaned
            final_command = command
            break
        else:
            previous_attempts.append((command, reason))
            if verbose:
                print("   Reflecting — trying different approach...")

    if not final_raw:
        if verbose:
            print("\nAll attempts failed.")
        return "Could not retrieve useful output after 3 attempts.\n" + \
               "\n".join(f"Attempt {i+1}: {c} -> {e}" for i, (c, e) in enumerate(previous_attempts))

    truncated_for_llm = final_cleaned[:8000] + "\n\n[... output truncated ...]" if len(final_cleaned) > 8000 else final_cleaned
    if verbose:
        print("\nSummarising result...", end=" ", flush=True)
    summary = _summarise(user_query, final_command, truncated_for_llm)
    if verbose:
        print("done")

    txt_path, csv_path = _save_outputs(
        user_query, final_command, final_raw, final_cleaned,
        summary, len(previous_attempts) + 1, timestamp,
    )
    if verbose:
        print(f"Saved: {txt_path.name}")
        if csv_path:
            print(f"CSV:   {csv_path.name}")
        print("─" * 50)
        print(f"\nSummary: {summary}")

    return (
        f"Query:    {user_query}\n"
        f"Command:  {final_command}\n"
        f"Attempts: {len(previous_attempts) + 1}\n"
        f"Time:     {timestamp}\n"
        f"{'─' * 60}\n\n"
        f"SUMMARY:\n{summary}\n\n"
        f"{'─' * 60}\n\n"
        f"RAW OUTPUT (truncated for display):\n{truncated_for_llm}"
    )


if __name__ == "__main__":
    print(run_vcf_query("Get me variants from second chromosome from base 5.5M to 5.51M"))
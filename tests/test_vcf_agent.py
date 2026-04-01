"""
tests/test_vcf_agent.py
------------------------
Tests for agents/vcf_agent.py — chromosome detection, safety validation,
output cleaning. Does NOT make live S3 calls.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ── Chromosome detection ───────────────────────────────────────────────────────

def test_detect_chromosome_ordinal():
    from agents.vcf_agent import _detect_chromosome
    assert _detect_chromosome("Get variants from second chromosome") == "2"
    assert _detect_chromosome("first chromosome") == "1"
    assert _detect_chromosome("third chromosome") == "3"
    assert _detect_chromosome("twenty-second chromosome") == "22"

def test_detect_chromosome_explicit():
    from agents.vcf_agent import _detect_chromosome
    assert _detect_chromosome("chr2 variants") == "2"
    assert _detect_chromosome("chromosome 5") == "5"
    assert _detect_chromosome("chrX") == "X"
    assert _detect_chromosome("chromosome X") == "X"

def test_detect_chromosome_none():
    from agents.vcf_agent import _detect_chromosome
    assert _detect_chromosome("find male individuals") is None
    assert _detect_chromosome("how many samples exist") is None

def test_resolve_vcf_file_chr2():
    from agents.vcf_agent import _resolve_vcf_file
    url = _resolve_vcf_file("Get variants from second chromosome", None)
    assert "chr2" in url
    assert "s3://" in url

def test_resolve_vcf_file_explicit():
    from agents.vcf_agent import _resolve_vcf_file
    custom = "s3://mybucket/custom.vcf.gz"
    assert _resolve_vcf_file("any query", custom) == custom

def test_resolve_vcf_file_fallback():
    from agents.vcf_agent import _resolve_vcf_file
    from config.settings import DEFAULT_VCF_FILE
    url = _resolve_vcf_file("no chromosome mentioned", None)
    assert url == DEFAULT_VCF_FILE


# ── Command safety ─────────────────────────────────────────────────────────────

def test_run_command_rejects_non_bcftools():
    from agents.vcf_agent import _run_command
    out, err, ok = _run_command("ls -la")
    assert not ok
    assert "bcftools" in err.lower()

def test_run_command_rejects_semicolon():
    from agents.vcf_agent import _run_command
    out, err, ok = _run_command("bcftools view file.vcf; rm -rf /")
    assert not ok
    assert ";" in err

def test_run_command_rejects_rm():
    from agents.vcf_agent import _run_command
    out, err, ok = _run_command("bcftools view file.vcf && rm -rf /")
    assert not ok

def test_run_command_rejects_pipe_injection():
    from agents.vcf_agent import _run_command
    out, err, ok = _run_command("bcftools view file.vcf $(cat /etc/passwd)")
    assert not ok

def test_run_command_rejects_backtick():
    from agents.vcf_agent import _run_command
    out, err, ok = _run_command("bcftools view `whoami`")
    assert not ok


# ── Output observation ─────────────────────────────────────────────────────────

def test_is_useful_output_empty():
    from agents.vcf_agent import _is_useful_output
    useful, reason = _is_useful_output("")
    assert not useful

def test_is_useful_output_header_only():
    from agents.vcf_agent import _is_useful_output
    header_only = "##fileformat=VCFv4.1\n##FILTER=<ID=PASS>\n#CHROM\tPOS\tID\n"
    useful, reason = _is_useful_output(header_only)
    assert not useful
    assert "header" in reason.lower()

def test_is_useful_output_with_data():
    from agents.vcf_agent import _is_useful_output
    with_data = (
        "##fileformat=VCFv4.1\n"
        "#CHROM\tPOS\tID\tREF\tALT\n"
        "2\t5500302\trs10929519\tG\tA\n"
    )
    useful, reason = _is_useful_output(with_data)
    assert useful

def test_is_useful_output_error_prefix():
    from agents.vcf_agent import _is_useful_output
    useful, _ = _is_useful_output("❌ Rejected: command failed")
    assert not useful


# ── Output cleaning ────────────────────────────────────────────────────────────

def test_clean_vcf_output_strips_meta():
    from agents.vcf_agent import _clean_vcf_output
    # Build fake VCF with 10 ## lines
    meta_lines = [f"##meta{i}=value{i}" for i in range(10)]
    header = "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\t" + "\t".join(f"SAMPLE{j}" for j in range(2504))
    data = "2\t5500302\trs10929519\tG\tA\t100\tPASS\tAF=0.64\tGT\t" + "\t".join(["0|1"] * 2504)
    raw = "\n".join(meta_lines) + "\n" + header + "\n" + data

    cleaned = _clean_vcf_output(raw)
    lines = cleaned.splitlines()

    # Should keep at most 5 ## lines
    meta_count = sum(1 for l in lines if l.startswith("##"))
    assert meta_count <= 5

    # Should trim sample columns
    header_line = next(l for l in lines if l.startswith("#CHROM") or l.startswith("CHROM"))
    assert "[+2504 sample columns]" in header_line

def test_vcf_to_csv_basic():
    from agents.vcf_agent import _vcf_to_csv
    cleaned = (
        "##fileformat=VCFv4.1\n"
        "#CHROM\tPOS\tID\tREF\tALT\t[+2504 sample columns]\n"
        "2\t5500302\trs10929519\tG\tA\t[data]\n"
    )
    csv_out = _vcf_to_csv(cleaned)
    assert csv_out is not None
    assert "CHROM" in csv_out
    assert "5500302" in csv_out

def test_vcf_to_csv_header_only_returns_none():
    from agents.vcf_agent import _vcf_to_csv
    header_only = "##fileformat=VCFv4.1\n#CHROM\tPOS\tID\n"
    assert _vcf_to_csv(header_only) is None

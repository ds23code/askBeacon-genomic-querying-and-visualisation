"""
main.py - CLI entry point for the Genomic AI Agents project.

Agents:
  vcf     — Agent 1: query 1000 Genomes VCF data via bcftools (ReAct loop)
  beacon  — Agent 2: build Beacon v2 query JSON via FAISS + Ollama
  join    — Agent 3: merge VCF + Beacon outputs into a unified table
  execute — Agent 4: generate + run matplotlib visualisation from plain English
  both    — run vcf + beacon together on the same query

Usage:
    # Agent 1 — VCF
    python main.py -a vcf -q "Get me variants from second chromosome from base 5.5M to 5.51M"

    # Agent 2 — Beacon
    python main.py -a beacon -q "Find male individuals with regional failure"
    python main.py -a beacon -q "How many individuals are from Northern Ireland?"
    python main.py -a beacon -q "Do any Europeans with breast cancer exist?"

    # Agent 3 — Joiner (auto-detects most recent VCF + Beacon outputs)
    python main.py -a join

    # Agent 3 — Joiner with explicit files
    python main.py -a join --vcf-file outputs/20260310_vcf.csv --beacon-file outputs/20260310_beacon.txt

    # Agent 4 — Executor
    python main.py -a execute -q "Plot allele frequency by ancestry group as a bar chart"
    python main.py -a execute -q "Show variant type distribution" --csv-file outputs/20260310_joined.csv

    # Both Agent 1 + 2
    python main.py -a both -q "Get variants on chromosome 2"

    # Interactive mode
    python main.py -a beacon
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def _build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for the CLI."""
    parser = argparse.ArgumentParser(
        description="Genomic AI Agents — plain English interface for genomic data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--agent", "-a",
        choices=["vcf", "beacon", "both", "join", "execute"],
        default="beacon",
        help="Which agent to run (default: beacon)",
    )
    parser.add_argument(
        "--query", "-q",
        type=str, default=None,
        help="Plain English query (required for vcf, beacon, both, execute).",
    )
    parser.add_argument(
        "--vcf",
        type=str, default=None,
        help="Explicit VCF/S3 path (VCF agent only). Defaults to auto-detection.",
    )
    parser.add_argument(
        "--vcf-file",
        type=str, default=None,
        dest="vcf_file",
        help="Path to VCF CSV output file (Joiner agent only).",
    )
    parser.add_argument(
        "--beacon-file",
        type=str, default=None,
        dest="beacon_file",
        help="Path to Beacon output file (Joiner agent only).",
    )
    parser.add_argument(
        "--csv-file",
        type=str, default=None,
        dest="csv_file",
        help="Path to CSV input file (Executor agent only).",
    )
    return parser


def main() -> None:
    """Parse arguments and dispatch to the requested agent."""
    parser = _build_parser()
    args = parser.parse_args()

    # Agents that need a query
    needs_query = {"vcf", "beacon", "both", "execute"}

    query = args.query
    if args.agent in needs_query and not query:
        print("Enter your query: ", end="", flush=True)
        query = input().strip()
    if args.agent in needs_query and not query:
        print("No query provided. Exiting.")
        sys.exit(1)

    print()

    # Agent 1: VCF
    if args.agent in ("vcf", "both"):
        from agents.vcf_agent import run_vcf_query
        result = run_vcf_query(query, vcf_file=args.vcf)
        if args.agent == "vcf":
            print(result)

    # Agent 2: Beacon
    if args.agent in ("beacon", "both"):
        from agents.beacon_agent import run_beacon_query
        result = run_beacon_query(query)
        print("\nBeacon v2 Query JSON:")
        print(json.dumps(result, indent=2))

    # Agent 3: Joiner
    if args.agent == "join":
        from agents.joiner_agent import run_joiner
        result = run_joiner(
            vcf_csv_path=args.vcf_file,
            beacon_json_path=args.beacon_file,
        )
        print(f"\nJoined {result['row_count']} rows")
        print(f"CSV: {result['csv_path']}")
        print(f"Summary: {result['summary']}")

    # Agent 4: Executor
    if args.agent == "execute":
        from agents.executor_agent import run_executor
        result = run_executor(
            request=query,
            csv_path=args.csv_file,
        )
        if result["success"]:
            print(f"\nPlot saved: {result['plot_path']}")
            print(f"Code saved: {result['code_path']}")
        else:
            print(f"\nExecution failed: {result['error']}")
            print(f"Code saved for inspection: {result['code_path']}")


if __name__ == "__main__":
    main()
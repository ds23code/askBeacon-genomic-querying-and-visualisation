"""
tests/run_tests.py
------------------
Simple test runner — run all tests and print a summary.

Usage:
    python tests/run_tests.py

    # Or with pytest (recommended):
    pip install pytest
    python -m pytest tests/ -v
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

def main():
    print("=" * 60)
    print("Genomic AI Agents — Test Suite")
    print("=" * 60)

    # Check if pytest is available
    try:
        import pytest
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/", "-v", "--tb=short"],
            cwd=ROOT,
        )
        sys.exit(result.returncode)
    except ImportError:
        print("pytest not installed. Install with: pip install pytest")
        print("Running basic import checks instead...\n")

    # Fallback: just check all modules import cleanly
    modules = [
        "config.settings",
        "ontology.ontology_lookup",
        "agents.vcf_agent",
        "agents.beacon_agent",
        "agents.joiner_agent",
        "agents.executor_agent",
    ]

    ok = True
    for mod in modules:
        try:
            __import__(mod)
            print(f"  ✅  {mod}")
        except Exception as e:
            print(f"  ❌  {mod}: {e}")
            ok = False

    print()
    if ok:
        print("All modules import cleanly.")
    else:
        print("Some modules failed to import — see errors above.")
        sys.exit(1)

if __name__ == "__main__":
    main()

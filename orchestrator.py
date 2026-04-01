"""
orchestrator.py – Main decision agent.

Given a plain English query, it:
  - Decides which agents to run (VCF, Beacon, Join, Executor)
  - Executes them in the correct order
  - Returns a final summary + any generated files
  - Saves results to memory for follow-up.
"""

import json
import re
from pathlib import Path

import requests

from config.settings import OLLAMA_BASE_URL, OLLAMA_MODEL, OUTPUTS_DIR
from agents.vcf_agent import run_vcf_query
from agents.beacon_agent import run_beacon_query
from agents.joiner_agent import run_joiner
from agents.executor_agent import run_executor
from memory import save_result, get_last_result


def _ollama(prompt: str, system: str = "") -> str:
    """Helper to call the local Ollama instance."""
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


def plan_actions(query: str) -> list[str]:
    """
    Ask the LLM to decide which agents to run.

    Returns a list of actions: e.g., ['vcf', 'beacon', 'join', 'execute'].

    The system prompt and fallback logic help avoid incorrectly including
    the Beacon agent when the query is purely about variants.
    """
    system = (
        "You are a workflow planner. Given a user query about genomic data, decide which "
        "of the following agents are needed: vcf, beacon, join, execute. "
        "- 'vcf': if the query asks for actual variant data (positions, alleles). "
        "- 'beacon': if the query asks for individual/cohort metadata (sex, disease, ancestry). "
        "- 'join': if both vcf and beacon were used, to combine them. "
        "- 'execute': if the query asks for a plot or visualisation. "
        "Return ONLY a JSON list of strings, e.g., ['vcf', 'execute']."
        "Do not include beacon unless the query explicitly asks about individuals, diseases, or population statistics."
    )
    prompt = f'User query: "{query}"\nActions:'
    raw = _ollama(prompt, system)

    try:
        m = re.search(r"\[.*?\]", raw, re.DOTALL)
        if m:
            actions = json.loads(m.group())
            # Sanity check: if query contains variant words but not individual words, remove beacon
            if "variant" in query.lower() or "chrom" in query.lower():
                if "beacon" in actions and not any(
                        word in query.lower() for word in ["male", "female", "disease", "asthma", "cancer", "ancestry"]
                ):
                    actions = [a for a in actions if a != "beacon"]
            return actions
    except Exception:
        pass

    # Fallback if LLM fails to produce JSON
    if re.search(r"chr(?:omosome)?\s*\d+|variant", query, re.IGNORECASE):
        return ['vcf']
    if re.search(r"male|female|disease|asthma|cancer|ancestry", query, re.IGNORECASE):
        return ['beacon']
    return []


def run_workflow(query: str, verbose: bool = True, actions_override: list[str] | None = None) -> dict:
    """
    Orchestrate the agents based on the plan (or override).

    Args:
        query: The user's natural language question.
        verbose: Print progress messages.
        actions_override: If provided, use this list of agents instead of planning.

    Returns:
        A dictionary containing results, file paths, and a final summary.
        The result is also saved to memory.
    """
    if actions_override is not None:
        actions = actions_override
    else:
        actions = plan_actions(query)

    if not actions:
        return {"error": "No agents matched the query.", "actions": []}

    results = {"query": query, "actions": actions, "files": {}}

    vcf_csv_path = None
    beacon_json_path = None
    joined_csv_path = None

    for action in actions:
        if action == 'vcf':
            # Run VCF agent – it saves its own outputs
            vcf_result = run_vcf_query(query, verbose=verbose)

            # Find the most recent CSV that looks like VCF output
            import time
            from agents.executor_agent import _find_latest_csv
            vcf_csv_path = _find_latest_csv("*_vcf.csv")
            if not vcf_csv_path:
                # fallback to any CSV created in the last few seconds
                latest = _find_latest_csv("*.csv")
                if latest and (time.time() - latest.stat().st_mtime) < 5:
                    vcf_csv_path = latest

            results["files"]["vcf_csv"] = str(vcf_csv_path) if vcf_csv_path else None
            results["vcf_summary"] = vcf_result

        elif action == 'beacon':
            # Run Beacon agent
            beacon_result = run_beacon_query(query, verbose=verbose)
            from agents.joiner_agent import _find_latest_output
            beacon_json_path = _find_latest_output("*beacon*.txt")
            results["files"]["beacon_json"] = str(beacon_json_path) if beacon_json_path else None
            results["beacon_result"] = beacon_result

        elif action == 'join':
            if vcf_csv_path and beacon_json_path:
                join_result = run_joiner(
                    vcf_csv_path=vcf_csv_path,
                    beacon_json_path=beacon_json_path,
                    verbose=verbose
                )
                results["join_result"] = join_result
                joined_csv_path = join_result.get("csv_path")
                results["files"]["joined_csv"] = joined_csv_path
            else:
                results["join_error"] = "Cannot join: missing VCF or Beacon output."

        elif action == 'execute':
            # Determine which CSV to use: joined if available, otherwise VCF, otherwise any CSV
            csv_to_use = None
            if joined_csv_path and Path(joined_csv_path).exists():
                csv_to_use = joined_csv_path
            elif vcf_csv_path and Path(vcf_csv_path).exists():
                csv_to_use = vcf_csv_path
            else:
                from agents.executor_agent import _find_latest_csv
                csv_to_use = _find_latest_csv("*.csv")

            if csv_to_use:
                exec_result = run_executor(request=query, csv_path=csv_to_use, verbose=verbose)
                results["executor_result"] = exec_result
                results["files"]["plot"] = exec_result.get("plot_path")
                results["files"]["plot_code"] = exec_result.get("code_path")
            else:
                results["execute_error"] = "No CSV found to visualise."

    # Build a final summary that combines all steps
    final_summary = f"Workflow executed: {', '.join(actions)}\n"
    for key, value in results.items():
        if key == "vcf_summary" and value:
            summary_part = value.split('SUMMARY:')[-1][:300]
            final_summary += f"\nVCF summary: {summary_part}"
        elif key == "beacon_result" and isinstance(value, dict):
            filters = value.get('query', {}).get('requestParameters', {}).get('filters', [])
            final_summary += f"\nBeacon filters: {filters}"
        elif key == "join_result" and isinstance(value, dict):
            final_summary += f"\nJoined {value.get('row_count', 0)} rows."
        elif key == "executor_result" and isinstance(value, dict):
            if value.get("success"):
                final_summary += f"\nPlot saved: {value.get('plot_path')}"
            else:
                final_summary += f"\nPlot failed: {value.get('error')}"
    results["final_summary"] = final_summary

    # Save to memory
    save_result(query, results)
    return results


if __name__ == "__main__":
    # Example usage
    res = run_workflow("Get variants on chromosome 2 and plot the allele frequencies")
    print(json.dumps(res, indent=2, default=str))
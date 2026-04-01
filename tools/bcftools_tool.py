"""
tools/bcftools_tool.py
----------------------
Legacy CrewAI tool wrapper for bcftools command execution.

STATUS: Not used by the current agents (vcf_agent.py calls bcftools directly).
Kept for reference — useful if you want to integrate bcftools into a
CrewAI-based workflow for agents 3 or 4.

The safety validation logic here was the basis for _run_command() in vcf_agent.py.
"""

import subprocess
from pathlib import Path


# Forbidden shell injection tokens
_FORBIDDEN = [";", "&&", "||", "`", "$(", "rm ", "mv ", "dd ", ">"]

# Output size limit
MAX_OUTPUT_CHARS = 8000

# Execution timeout (seconds)
TIMEOUT = 120


def run_bcftools(command: str) -> str:
    """
    Validate and execute a bcftools command.

    Security checks (in order):
      1. Command must start with 'bcftools'
      2. No forbidden shell injection tokens
      3. 120-second timeout
      4. Output truncated at 8,000 characters

    Args:
        command: A bcftools command string, e.g.
                 "bcftools view s3://bucket/file.vcf.gz --regions 2:5500000-5510000"

    Returns:
        stdout output as a string, or an error message starting with "Warning" or "Error".
    """
    if not command.startswith("bcftools"):
        return f"Rejected: command must start with bcftools. Got: {command!r}"

    for token in _FORBIDDEN:
        if token in command:
            return f"Rejected: forbidden token '{token}' in command."

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
        )
        output = result.stdout.strip()

        if result.returncode != 0:
            return f"bcftools error:\n{result.stderr.strip()}"

        if len(output) > MAX_OUTPUT_CHARS:
            output = output[:MAX_OUTPUT_CHARS] + "\n\n[... output truncated ...]"

        return output or "(no output)"

    except subprocess.TimeoutExpired:
        return f"Command timed out after {TIMEOUT} seconds."
    except Exception as e:
        return f"Error: {e}"
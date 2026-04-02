"""
agents/executor_agent.py
------------------------
Agent 4 — Code Executor / Visualisation Generator.
Inspects CSV -> generates matplotlib/pandas code -> validates safety -> executes -> saves plot.
Now with improved filtering syntax, broader plot support, and automatic error recovery.
"""

import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config.settings import OLLAMA_BASE_URL, OLLAMA_MODEL, OUTPUTS_DIR

OUTPUTS_DIR.mkdir(exist_ok=True)

# Dangerous patterns blocked for security
_BLOCKED_PATTERNS = [
    r"\bsubprocess\b", r"\bos\.system\b", r"\bos\.popen\b",
    r"\beval\b", r"\bexec\b", r"\b__import__\b",
    r"\brequests\b", r"\burllib\b", r"\bsocket\b",
    r"\bshutil\b", r"\brmdir\b", r"\bunlink\b", r"\bos\.remove\b",
]

# Pattern to catch chained comparisons like 1500000 <= df['POS'] <= 1510000
_CHAINED_COMPARISON = re.compile(
    r"(\d+(?:\.\d+)?)\s*<=\s*([\w.\[\]'\"_]+)\s*<=\s*(\d+(?:\.\d+)?)"
)


def _ollama(prompt: str, system: str = "") -> str:
    """Send a prompt to Ollama and return the response."""
    resp = requests.post(
        f"{OLLAMA_BASE_URL}/api/generate",
        json={
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "system": system,
            "stream": False,
            "options": {"temperature": 0.1}
        },
        timeout=90,
    )
    resp.raise_for_status()
    return resp.json()["response"].strip()


def _find_latest_csv(pattern: str = "*.csv") -> Path | None:
    """Find the most recently created CSV file in outputs/."""
    matches = sorted(OUTPUTS_DIR.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return matches[0] if matches else None


def _extract_code_block(raw: str) -> str:
    """Extract Python code from a response that may contain markdown code blocks."""
    m = re.search(r"```(?:python)?\s*(.*?)```", raw, re.DOTALL | re.IGNORECASE)
    if m:
        code = m.group(1).strip()
        code = re.sub(r"^```|```$", "", code)
        return code
    if "import" in raw or "plt." in raw or "pd." in raw or "df." in raw:
        return raw.strip()
    return ""


def _fix_chained_comparisons(code: str) -> str:
    """
    Rewrite expressions like 'lower <= df['col'] <= upper' into
    '(df['col'] >= lower) & (df['col'] <= upper)' to avoid pandas ambiguity.
    """
    def replacer(match):
        lower = match.group(1)
        col_expr = match.group(2)
        upper = match.group(3)
        return f"({col_expr} >= {lower}) & ({col_expr} <= {upper})"

    # Apply to all occurrences in the code
    return _CHAINED_COMPARISON.sub(replacer, code)


def _inspect_csv(csv_path: Path) -> dict:
    """Extract columns, data types, and sample rows from the CSV."""
    import pandas as pd
    try:
        df = pd.read_csv(csv_path, nrows=10)
        columns = df.columns.tolist()
        numeric_cols = df.select_dtypes(include=['number']).columns.tolist()
        categorical_cols = []
        for col in df.select_dtypes(include=['object']).columns:
            if df[col].nunique() <= 10:
                categorical_cols.append(col)
        row_count = len(pd.read_csv(csv_path))
        sample_rows = df.head(5).to_dict(orient='records')
        # Check if INFO column exists and contains AF=
        has_af = False
        if 'INFO' in columns:
            info_vals = df['INFO'].dropna().head()
            has_af = any('AF=' in str(v) for v in info_vals)
        return {
            "columns": columns,
            "numeric_cols": numeric_cols,
            "categorical_cols": categorical_cols,
            "row_count": row_count,
            "sample_rows": sample_rows,
            "has_af": has_af,
        }
    except Exception as e:
        return {"error": str(e)}


def _generate_code(csv_path: Path, request: str, csv_info: dict,
                   output_dir: Path, timestamp: str) -> str:
    """Ask Ollama to generate Python code for the requested visualisation."""
    plot_path = output_dir / f"{timestamp}_plot.png"
    row_count = csv_info.get("row_count", 0)
    columns = csv_info.get("columns", [])
    sample_rows = csv_info.get("sample_rows", [])[:5]
    sample_str = "\n".join(str(r) for r in sample_rows)
    has_af = csv_info.get("has_af", False)
    numeric_cols = csv_info.get("numeric_cols", [])
    categorical_cols = csv_info.get("categorical_cols", [])

    col_desc = "\n".join(f"- {col}" for col in columns[:20])

    system = (
        "You are a Python data visualisation expert using pandas and matplotlib.\n"
        "Write clean, complete, runnable Python code.\n"
        f"- Load data from: {csv_path}\n"
        f"- Save plot to EXACTLY: {plot_path}\n"
        "- Use plt.savefig() NOT plt.show()\n"
        "- Handle missing values with try/except\n"
        "- Use the default matplotlib style; do NOT call plt.style.use()\n"
        "- Add proper axis labels and title\n"
        "- Do NOT use subprocess, eval, exec, requests, or open()\n"
        "- Import ONLY pandas, matplotlib, numpy\n"
        "- Output ONLY Python code — no explanation\n"
        f"- The dataset has {row_count} rows.\n"
        "- **CRITICAL FOR FILTERING**: Always use the pattern `(df['col'] >= lower) & (df['col'] <= upper)`. "
        "Never write `lower <= df['col'] <= upper` because pandas cannot evaluate that.\n"
        "- If the dataset is small (<=10 rows), a bar chart or point plot is fine.\n"
        "- If the dataset is larger, consider histograms or scatter plots.\n"
        "- For bar charts with counts, use `df['categorical_column'].value_counts().plot(kind='bar')`.\n"
        "- For allele frequency, extract AF from INFO column if present, then plot.\n"
        f"- Available columns: {', '.join(columns)}\n"
    )
    if has_af:
        system += (
            "- The INFO column contains key=value pairs like 'AF=0.0006;...'. Extract AF with:\n"
            "  df['AF'] = df['INFO'].str.extract(r'AF=([0-9.]+)').astype(float)\n"
        )
    if numeric_cols:
        system += f"- Numeric columns: {numeric_cols}. Use them for y-axis values.\n"
    if categorical_cols:
        system += f"- Categorical columns: {categorical_cols}. Use them for grouping or x-axis labels.\n"

    prompt = (
        f"CSV file: {csv_path}\n"
        f"Columns:\n{col_desc}\n"
        f"Total rows: {row_count}\n"
        f"Sample rows (first 5):\n{sample_str}\n\n"
        f'User request: "{request}"\n\n'
        "Write the Python code:"
    )
    code = _extract_code_block(_ollama(prompt, system))
    # Remove any stray plt.style.use lines
    code = re.sub(r"plt\.style\.use\([^)]*\)", "# style removed to avoid errors", code)
    # Fix chained comparisons
    code = _fix_chained_comparisons(code)
    return code


def _validate_code(code: str) -> tuple[bool, str]:
    """Check for dangerous patterns and ensure plt.savefig is present."""
    if not code.strip():
        return False, "Generated code is empty"
    if "plt.savefig" not in code and "savefig" not in code:
        return False, "Code does not call plt.savefig()"
    for pattern in _BLOCKED_PATTERNS:
        if re.search(pattern, code):
            return False, f"Blocked pattern: {pattern}"
    return True, "OK"


def _execute_code(code: str, code_path: Path, timeout: int = 60) -> tuple[bool, str]:
    """Save the code to a file and run it in a subprocess."""
    code_path.write_text(code, encoding="utf-8")
    try:
        result = subprocess.run(
            [sys.executable, str(code_path)],
            capture_output=True, text=True, timeout=timeout,
            cwd=str(code_path.parent),
        )
        if result.returncode == 0:
            return True, result.stdout.strip()
        return False, result.stderr.strip() or f"Exit code {result.returncode}"
    except subprocess.TimeoutExpired:
        return False, f"Timed out after {timeout} seconds."
    except Exception as e:
        return False, str(e)


def run_executor(request: str, csv_path: str | Path | None = None,
                 verbose: bool = True) -> dict:
    """
    Generate and execute visualisation code based on the request and CSV data.

    Args:
        request: Natural language visualisation request.
        csv_path: Path to CSV file. If None, auto-detect.
        verbose: Print progress messages.

    Returns:
        Dict with keys: success, plot_path, code_path, code, output, error.
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if verbose:
        print(f"\nExecutor Agent\nRequest: {request}\n{'─'*50}")

    # Determine the CSV to use
    data_file = None
    if csv_path:
        data_file = Path(csv_path)
    else:
        data_file = _find_latest_csv("*_vcf.csv")
        if not data_file:
            data_file = _find_latest_csv("*.csv")
    if data_file is None:
        raise FileNotFoundError("No CSV found in outputs/.")
    if verbose:
        print(f"Data: {data_file.name}")

    if verbose:
        print("Inspecting CSV structure...", end=" ", flush=True)
    csv_info = _inspect_csv(data_file)
    if verbose:
        print(f"done — {csv_info.get('row_count', '?')} rows, {len(csv_info.get('columns', []))} columns")
        if csv_info.get('numeric_cols'):
            print(f"   Numeric columns: {csv_info['numeric_cols']}")
        if csv_info.get('categorical_cols'):
            print(f"   Categorical columns: {csv_info['categorical_cols']}")

    # Generate code with retry on validation failure
    code = None
    attempts = 0
    while attempts < 2:
        if verbose:
            print(f"Generating visualisation code (attempt {attempts+1})...", end=" ", flush=True)
        code = _generate_code(data_file, request, csv_info, OUTPUTS_DIR, timestamp)
        if verbose:
            print("done")
        safe, reason = _validate_code(code)
        if safe:
            break
        else:
            if verbose:
                print(f"   Validation failed: {reason}. Retrying with simplified prompt...")
            attempts += 1
            # For the second attempt, we could modify the system prompt, but the function
            # already uses the same prompt; the retry may still help due to temperature randomness.

    if not code or not safe:
        if verbose:
            print("Could not generate valid code.")
        return {"success": False, "error": f"Code generation failed after attempts: {reason}",
                "plot_path": None, "code_path": None, "code": code}

    code_path = OUTPUTS_DIR / f"{timestamp}_plot_code.py"
    plot_path = OUTPUTS_DIR / f"{timestamp}_plot.png"

    if verbose:
        print("Executing code...", end=" ", flush=True)
    success, output = _execute_code(code, code_path, timeout=60)
    if verbose:
        print("done" if success else f"failed — {output[:80]}")

    # Save a log of the execution
    (OUTPUTS_DIR / f"{timestamp}_executor.txt").write_text(
        f"Request: {request}\nCSV: {data_file.name}\nSuccess: {success}\n"
        f"Time: {timestamp}\n{'─'*60}\n\nCODE:\n{code}\n\nOUTPUT:\n{output}\n"
    )

    if verbose:
        if success and plot_path.exists():
            print(f"Plot: {plot_path.name}")
        print(f"Code: {code_path.name}\n{'─'*50}")

    return {
        "success": success,
        "plot_path": str(plot_path) if (success and plot_path.exists()) else None,
        "code_path": str(code_path),
        "code": code,
        "output": output,
        "error": output if not success else None
    }


if __name__ == "__main__":
    result = run_executor("Bar chart of variant type counts (SNP, INDEL, SV)")
    print(f"{'Success' if result['success'] else 'Failure'}: {result.get('plot_path') or result.get('error')}")
"""
tests/test_executor_agent.py
-----------------------------
Tests for agents/executor_agent.py — code safety validation, CSV inspection,
code extraction. Does NOT run generated code or make Ollama calls.
"""
import csv
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config.settings import OUTPUTS_DIR


# ── Code safety validation ─────────────────────────────────────────────────────

def test_validate_code_blocks_subprocess():
    from agents.executor_agent import _validate_code
    code = "import subprocess\nsubprocess.run(['ls'])"
    safe, reason = _validate_code(code, OUTPUTS_DIR)
    assert not safe

def test_validate_code_blocks_eval():
    from agents.executor_agent import _validate_code
    code = "result = eval('1+1')"
    safe, reason = _validate_code(code, OUTPUTS_DIR)
    assert not safe

def test_validate_code_blocks_exec():
    from agents.executor_agent import _validate_code
    code = "exec('import os')"
    safe, reason = _validate_code(code, OUTPUTS_DIR)
    assert not safe

def test_validate_code_blocks_no_savefig():
    from agents.executor_agent import _validate_code
    code = "import pandas as pd\ndf = pd.read_csv('data.csv')\nprint(df.head())"
    safe, reason = _validate_code(code, OUTPUTS_DIR)
    assert not safe
    assert "savefig" in reason.lower()

def test_validate_code_passes_clean_code():
    from agents.executor_agent import _validate_code
    OUTPUTS_DIR.mkdir(exist_ok=True)
    plot_path = OUTPUTS_DIR / "test_plot.png"
    code = (
        "import pandas as pd\n"
        "import matplotlib\nmatplotlib.use('Agg')\n"
        "import matplotlib.pyplot as plt\n"
        f"df = pd.read_csv('data.csv')\n"
        f"plt.bar(['SNP', 'INDEL'], [10, 5])\n"
        f"plt.savefig('{plot_path}')\n"
    )
    safe, reason = _validate_code(code, OUTPUTS_DIR)
    assert safe, f"Clean code failed validation: {reason}"


# ── Code extraction ────────────────────────────────────────────────────────────

def test_extract_code_block_fenced():
    from agents.executor_agent import _extract_code_block
    raw = "Here is the code:\n```python\nimport pandas as pd\nprint('hello')\n```\nDone."
    code = _extract_code_block(raw)
    assert "import pandas" in code
    assert "```" not in code

def test_extract_code_block_plain():
    from agents.executor_agent import _extract_code_block
    raw = "import pandas as pd\nplt.savefig('output.png')"
    code = _extract_code_block(raw)
    assert "import pandas" in code


# ── CSV inspection ─────────────────────────────────────────────────────────────

def test_inspect_csv_basic():
    from agents.executor_agent import _inspect_csv
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "test.csv"
        with open(p, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["CHROM", "POS", "AF"])
            writer.writeheader()
            for i in range(10):
                writer.writerow({"CHROM": "2", "POS": str(5500000 + i), "AF": "0.5"})

        info = _inspect_csv(p)
        assert "CHROM" in info["columns"]
        assert "POS"   in info["columns"]
        assert "AF"    in info["columns"]
        assert info["row_count"] == 10
        assert len(info["sample_rows"]) <= 5

def test_inspect_csv_detects_numeric():
    from agents.executor_agent import _inspect_csv
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "test.csv"
        with open(p, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["ID", "AF", "COUNT"])
            writer.writeheader()
            for i in range(5):
                writer.writerow({"ID": f"rs{i}", "AF": "0.5", "COUNT": "42"})

        info = _inspect_csv(p)
        assert "AF" in info["numeric_cols"] or "COUNT" in info["numeric_cols"]

"""
memory.py – Simple JSON-based memory for the orchestrator.

Stores previous query results so that follow-up questions can use them.
"""

import json
from pathlib import Path
from datetime import datetime

MEMORY_FILE = Path(__file__).parent / "memory.json"


def save_result(query: str, result: dict) -> None:
    """Store the result of a query in memory.

    Args:
        query: The user's question.
        result: The output dictionary from run_workflow().
    """
    if not MEMORY_FILE.exists():
        with open(MEMORY_FILE, "w") as f:
            json.dump([], f)

    with open(MEMORY_FILE) as f:
        history = json.load(f)

    history.append({
        "timestamp": datetime.now().isoformat(),
        "query": query,
        "result": result
    })

    # Keep only the last 100 entries to avoid unbounded growth
    if len(history) > 100:
        history = history[-100:]

    with open(MEMORY_FILE, "w") as f:
        json.dump(history, f, indent=2)


def get_last_result() -> dict | None:
    """Return the most recent stored result."""
    if not MEMORY_FILE.exists():
        return None
    with open(MEMORY_FILE) as f:
        history = json.load(f)
    if not history:
        return None
    return history[-1]["result"]


def get_history(limit: int = 10) -> list[dict]:
    """Return the last `limit` entries from memory."""
    if not MEMORY_FILE.exists():
        return []
    with open(MEMORY_FILE) as f:
        history = json.load(f)
    return history[-limit:]
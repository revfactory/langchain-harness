from __future__ import annotations

import os
from pathlib import Path

MODEL_ID = os.getenv("LANGCHAIN_HARNESS_MODEL", "claude-opus-4-7")
THINKING_BUDGET = int(os.getenv("LANGCHAIN_HARNESS_THINKING_BUDGET", "8000"))
WORKSPACE_DIR = Path(os.getenv("LANGCHAIN_HARNESS_WORKSPACE", "_workspace"))

DEFAULT_SYSTEM_PROMPT = (
    "You are a deep coding agent powered by Claude Opus 4.7.\n"
    "You plan carefully, verify every step, and prefer minimal-diff edits.\n"
    "Before declaring completion, run the self-checklist injected by the harness."
)

from __future__ import annotations

import subprocess
from pathlib import Path

from langchain_core.tools import tool
from pydantic import BaseModel, Field


class ReadFileArgs(BaseModel):
    path: str = Field(description="Path to the file to read (absolute or relative to CWD).")
    max_lines: int = Field(default=2000, description="Maximum number of lines to return.")


@tool(args_schema=ReadFileArgs)
def read_file(path: str, max_lines: int = 2000) -> str:
    """Read a text file from disk, returning at most max_lines lines."""
    p = Path(path)
    if not p.exists():
        return f"ERROR: {path} does not exist"
    lines = p.read_text().splitlines()
    return "\n".join(lines[:max_lines])


class WriteFileArgs(BaseModel):
    path: str = Field(description="Path to the file to create or overwrite.")
    content: str = Field(description="Full content to write.")


@tool(args_schema=WriteFileArgs)
def write_file(path: str, content: str) -> str:
    """Overwrite a file with the provided content. Creates parent directories as needed."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return f"wrote {len(content)} bytes to {path}"


class BashArgs(BaseModel):
    command: str = Field(description="Shell command to run.")
    timeout: int = Field(default=60, description="Timeout in seconds.")


@tool(args_schema=BashArgs)
def bash(command: str, timeout: int = 60) -> str:
    """Execute a shell command. Use for testing, compilation, file inspection."""
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return f"TIMEOUT after {timeout}s"
    output = (result.stdout or "") + (result.stderr or "")
    return f"exit={result.returncode}\n{output[:8000]}"


def default_tools() -> list:
    return [read_file, write_file, bash]

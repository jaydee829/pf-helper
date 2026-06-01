"""Resolve the command that launches the MCP server, for client registration."""

from __future__ import annotations

import shutil
import sys
from collections.abc import Callable
from pathlib import Path


def server_command(
    which: Callable[[str], str | None] = shutil.which, executable: str = sys.executable
) -> list[str]:
    """Absolute command to run the stdio MCP server.

    Prefer the installed `pf-helper` console script (its resolved path avoids the
    `uv run` cwd problem under Claude Desktop). If it isn't on PATH (common when
    Desktop launches us without the venv activated), look for it next to the
    Python interpreter, where pip/uv install console scripts. Last resort:
    `python -m pf_helper`.
    """
    exe = which("pf-helper")
    if not exe:
        suffix = ".exe" if sys.platform == "win32" else ""
        candidate = Path(executable).parent / f"pf-helper{suffix}"
        if candidate.exists():
            exe = str(candidate)
    if exe:
        return [exe, "serve"]
    return [executable, "-m", "pf_helper", "serve"]

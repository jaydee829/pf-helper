"""Resolve the command that launches the MCP server, for client registration."""

from __future__ import annotations

import shutil
import sys
from collections.abc import Callable


def server_command(which: Callable[[str], str | None] = shutil.which) -> list[str]:
    """Absolute command to run the stdio MCP server.

    Prefer the installed `pf-helper` console script (its resolved path avoids the
    `uv run` cwd problem under Claude Desktop); fall back to `python -m pf_helper`.
    """
    exe = which("pf-helper")
    if exe:
        return [exe, "serve"]
    return [sys.executable, "-m", "pf_helper", "serve"]

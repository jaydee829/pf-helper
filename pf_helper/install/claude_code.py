"""Register the MCP server with the Claude Code CLI (`claude mcp add`)."""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable


def claude_code_argv(server_cmd: list[str]) -> list[str]:
    return ["claude", "mcp", "add", "pf-helper", "--", *server_cmd]


def register_claude_code(
    server_cmd: list[str],
    *,
    which: Callable[[str], str | None] = shutil.which,
    run: Callable[..., object] = subprocess.run,
) -> bool:
    """Run `claude mcp add` if the CLI is on PATH; return False if it's absent."""
    if which("claude") is None:
        return False
    run(claude_code_argv(server_cmd), check=True)
    return True

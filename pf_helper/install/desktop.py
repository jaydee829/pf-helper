"""Locate and update the Claude Desktop MCP config across platforms."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def desktop_config_path(platform: str = sys.platform, env: dict | None = None) -> Path | None:
    env = env if env is not None else dict(os.environ)
    if platform == "win32":
        local = env.get("LOCALAPPDATA")
        if local:
            pattern = "Packages/Claude_*/LocalCache/Roaming/Claude/claude_desktop_config.json"
            matches = sorted(Path(local).glob(pattern))
            if matches:
                return matches[0]  # MSIX/Store build (redirected path)
        appdata = env.get("APPDATA")
        return Path(appdata) / "Claude" / "claude_desktop_config.json" if appdata else None
    if platform == "darwin":
        home = env.get("HOME")
        return (
            Path(home) / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
            if home
            else None
        )
    return None  # no official Claude Desktop on Linux/other


def merge_server_entry(existing: dict, command: list[str], name: str = "pf-helper") -> dict:
    out = dict(existing)
    servers = dict(out.get("mcpServers") or {})
    servers[name] = {"command": command[0], "args": command[1:]}
    out["mcpServers"] = servers
    return out


def register_desktop(command: list[str], *, path: Path | None = None) -> Path:
    p = path or desktop_config_path()
    if p is None:
        raise RuntimeError(
            "Claude Desktop isn't available on this OS — use `--client claude-code`."
        )
    if p.exists():
        raw = p.read_text(encoding="utf-8")
        try:
            existing = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"{p} is not valid JSON; refusing to overwrite.") from exc
        backup = p.with_suffix(p.suffix + ".bak")
        backup.write_text(raw, encoding="utf-8")  # verbatim copy preserves original formatting
    else:
        existing = {}
        p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(merge_server_entry(existing, command), indent=2), encoding="utf-8")
    return p

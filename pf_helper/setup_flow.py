"""Interactive first-time setup: build index, capture config, register clients."""

from __future__ import annotations

import getpass
from collections.abc import Callable

from pf_helper import userconfig
from pf_helper.config import Config
from pf_helper.ingest.build import ensure_index
from pf_helper.install import claude_code, desktop
from pf_helper.install.server_cmd import server_command


def _yn(input_fn: Callable[[str], str], prompt: str, *, default: bool) -> bool:
    suffix = " [Y/n] " if default else " [y/N] "
    ans = input_fn(prompt + suffix).strip().lower()
    if not ans:
        return default
    return ans.startswith("y")


def run_setup(
    *,
    yes: bool = False,
    input_fn: Callable[[str], str] = input,
    getpass_fn: Callable[[str], str] = getpass.getpass,
) -> None:
    cfg = Config.from_env()
    print(f"Data dir:    {cfg.data_dir}")
    print(f"Config file: {userconfig.config_path()}")

    if not cfg.db_path.exists() and (
        yes or _yn(input_fn, "Build the rules index now? (~a few minutes)", default=True)
    ):
        ensure_index(cfg)

    if yes:
        print("Setup complete (non-interactive: index only).")
        return

    if _yn(input_fn, "Configure the Discord bot?", default=False):
        token = getpass_fn("Discord bot token: ").strip()
        disc: dict = {"token": token}
        gid = input_fn("Guild ID (optional, Enter to skip): ").strip()
        if gid:
            disc["guild_id"] = int(gid)
        userconfig.write_file_config({"discord": disc})
        print("Saved Discord config.")

    cmd = server_command()
    if _yn(input_fn, "Register the MCP server with Claude Desktop?", default=True):
        try:
            path = desktop.register_desktop(cmd)
            print(f"  Registered with Claude Desktop at {path}. Restart Desktop.")
        except RuntimeError as exc:
            print(f"  Skipped Desktop: {exc}")
    if _yn(input_fn, "Register the MCP server with Claude Code?", default=False):
        if claude_code.register_claude_code(cmd):
            print("  Registered with Claude Code.")
        else:
            print("  `claude` not found — run: " + " ".join(claude_code.claude_code_argv(cmd)))

    print("Setup complete.")

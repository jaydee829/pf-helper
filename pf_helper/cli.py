"""Unified `pf-helper` CLI. Bare invocation runs the MCP server (back-compat)."""

from __future__ import annotations

import argparse
import json


def _cmd_serve(args: argparse.Namespace) -> None:
    from pf_helper.server import main as serve_main

    serve_main()


def _cmd_bot(args: argparse.Namespace) -> None:
    from pf_helper.bot.main import main as bot_main

    bot_main()


def _cmd_ingest(args: argparse.Namespace) -> None:
    from pf_helper.config import Config
    from pf_helper.ingest.build import run_ingest

    run_ingest(Config.from_env(), refresh=args.refresh)


def _cmd_register(args: argparse.Namespace) -> None:
    from pf_helper.install import claude_code, desktop, server_cmd

    cmd = server_cmd.server_command()
    if args.client == "desktop":
        if args.print_only:
            print(json.dumps(desktop.merge_server_entry({}, cmd), indent=2))
            return
        path = desktop.register_desktop(cmd)
        print(f"Registered with Claude Desktop at {path}. Restart Desktop to load it.")
    else:  # claude-code
        argv = claude_code.claude_code_argv(cmd)
        if args.print_only:
            print(" ".join(argv))
            return
        if claude_code.register_claude_code(cmd):
            print("Registered with Claude Code.")
        else:
            print("`claude` CLI not found. Run this manually:\n  " + " ".join(argv))


def _cmd_print_config(args: argparse.Namespace) -> None:
    from pf_helper.install import desktop, server_cmd

    print(json.dumps(desktop.merge_server_entry({}, server_cmd.server_command()), indent=2))


def _cmd_setup(args: argparse.Namespace) -> None:
    from pf_helper.setup_flow import run_setup

    run_setup(yes=args.yes)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pf-helper", description="Pathfinder 2e rules assistant")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("serve", help="Run the MCP server").set_defaults(func=_cmd_serve)
    sub.add_parser("bot", help="Run the Discord bot").set_defaults(func=_cmd_bot)
    ing = sub.add_parser("ingest", help="Build/refresh the rules index")
    ing.add_argument("--refresh", action="store_true")
    ing.set_defaults(func=_cmd_ingest)
    reg = sub.add_parser("register", help="Register the MCP server with a client")
    reg.add_argument("--client", choices=["desktop", "claude-code"], required=True)
    reg.add_argument(
        "--print", dest="print_only", action="store_true", help="Print config instead of writing"
    )
    reg.set_defaults(func=_cmd_register)
    sub.add_parser("print-config", help="Print MCP config to paste manually").set_defaults(
        func=_cmd_print_config
    )
    st = sub.add_parser("setup", help="Interactive first-time setup")
    st.add_argument("--yes", action="store_true", help="Non-interactive: build index, skip prompts")
    st.set_defaults(func=_cmd_setup)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    if getattr(args, "func", None) is None:
        _cmd_serve(args)  # bare `pf-helper` -> serve (preserves existing Desktop wiring)
        return
    args.func(args)

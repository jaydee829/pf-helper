# PF_Helper — Turnkey Install & Multi-System Configuration (Design Spec)

**Date:** 2026-05-31
**Status:** Approved (brainstorming)
**Builds on:** the merged server + AON + Foundry-links + Discord bot + fuzzy cache on `main`.

## Goal

Make PF_Helper installable and configurable across Windows/macOS/Linux with
minimal friction, for both the maintainer's own machines and strangers who clone
it. After install, a single `pf-helper setup` should build the index, capture any
needed config, and register the MCP server with the user's Anthropic-ecosystem
clients — no hand-editing of `claude_desktop_config.json`, no platform-specific
path hunting.

## Audience & phasing

**Phased "both".** This spec is **Phase 1**: the portable foundation that serves
both the maintainer and self-hosters — user-scoped dirs, a config file, a unified
CLI with a setup/register flow, auto-build of the index, and cross-platform docs.
**Phase 2 (deferred to its own spec):** public distribution — PyPI/pipx
publishing and a Docker image — layered on this foundation without rework.

## Non-goals (Phase 1)

- No PyPI publish, no Docker image (Phase 2).
- No OS-keyring secret storage (deferred; env + config file chosen).
- No GUI/installer binary; the interface is a CLI.
- Stay in the Anthropic ecosystem: registration targets are **Claude Desktop**,
  **Claude Code CLI**, and the **Discord bot**. A generic "print config for any
  MCP client" capability exists only as a byproduct command, not a headline goal.
- No prebuilt-index distribution (auto-build on first run was chosen; this also
  sidesteps redistributing Foundry/AON-derived data).

---

## Component 1 — Directories & configuration

### Directory resolution

Today `Config.data_dir` defaults to `<repo>/data`, which breaks when the package
is installed as a tool (the install location isn't writable / isn't the repo).
New resolution order for the **data dir**:

1. `PF_HELPER_DATA_DIR` env → use it.
2. config-file `data_dir` → use it.
3. **Source checkout** (a `pyproject.toml` exists at the package's parent dir) →
   `<repo>/data` — preserves the current dev workflow (incl. an already-built
   local index).
4. Else (installed as a tool) → `platformdirs.user_data_dir("pf-helper")`
   (`%LOCALAPPDATA%\pf-helper`, `~/Library/Application Support/pf-helper`,
   `~/.local/share/pf-helper`).

The **config file** lives at `platformdirs.user_config_dir("pf-helper") /
"config.toml"` (regardless of data-dir source), unless `PF_HELPER_CONFIG`
overrides the path.

### Config file (`config.toml`)

Read with stdlib `tomllib`; written by `setup`/`register` via a small built-in
serializer (no write-dependency). Schema (all keys optional):

```toml
data_dir = "/abs/path"          # optional data-dir override

[discord]
token = "..."                    # bot token (chmod 600; never logged)
guild_id = 123456789             # optional fast guild command sync

[ask]
engine = "auto"                  # optional mirrors of PF_HELPER_ASK_*
cache_similarity = 0.5
```

### Precedence (everywhere)

**CLI flag > environment variable > config file > built-in default.** A single
`load_file_config() -> dict` reads the TOML once; `Config.from_env`,
`AnswerConfig.from_env`, and `BotConfig.from_env` each consult it as the layer
below env. Existing env var names are unchanged (`PF_HELPER_DATA_DIR`,
`PF_HELPER_ASK_*`, `DISCORD_BOT_TOKEN`, `PF_HELPER_DISCORD_GUILD_ID`).

### Module

`pf_helper/userconfig.py` (new): `config_path()`, `data_dir_default()`,
`load_file_config()`, `write_file_config(updates: dict)` (merge + atomic write +
`chmod 600` on POSIX). Pure/injectable (accepts explicit base dirs for tests).

---

## Component 2 — Unified `pf-helper` CLI

`pf_helper/cli.py` (new) with an `argparse` subcommand dispatcher; add
`pf_helper/__main__.py` (`from pf_helper.cli import main; main()`) so
`python -m pf_helper …` works.

Subcommands:
- `setup` — interactive orchestrator (see Component 4).
- `register --client {desktop,claude-code} [--print]` — Component 3.
- `serve` — run the MCP server (calls `server.main`).
- `bot` — run the Discord bot (calls `bot.main.main`).
- `ingest [--refresh]` — build/refresh the index (calls the ingest entry).
- `print-config` — emit the ready-to-paste MCP JSON + resolved command (the
  generic-client byproduct).

**Back-compat (critical):** change the `pf-helper` console script from
`pf_helper.server:main` to `pf_helper.cli:main`, and make the CLI **default to
`serve` when invoked with no subcommand**. Bare `pf-helper` therefore still
starts the MCP server, so the maintainer's existing Claude Desktop registration
keeps working untouched. The `pf-helper-ingest` and `pf-helper-bot` scripts
remain as-is (aliases); `pf-helper ingest` / `pf-helper bot` are added on top.

`pyproject.toml`: `pf-helper = "pf_helper.cli:main"` (others unchanged); add
`platformdirs` to core `dependencies`.

---

## Component 3 — MCP client registration (`pf_helper/install/`)

### Server-command resolution (`install/server_cmd.py`)

`server_command() -> list[str]`: prefer the installed console script
(`shutil.which("pf-helper")`) → `[<abs path>, "serve"]`; fallback
`[sys.executable, "-m", "pf_helper", "serve"]`. Using the resolved absolute
script path is exactly the fix for the `uv run` cwd gotcha (Desktop doesn't apply
cwd).

### Claude Desktop (`install/desktop.py`)

`desktop_config_path() -> Path | None` per OS:
- **Windows:** prefer the MSIX redirected path if present — glob
  `%LOCALAPPDATA%\Packages\Claude_*\LocalCache\Roaming\Claude\claude_desktop_config.json`;
  else `%APPDATA%\Claude\claude_desktop_config.json`.
- **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`.
- **Linux:** `None` — no official Claude Desktop; `register --client desktop`
  errors with "Claude Desktop isn't available on Linux — use
  `--client claude-code`."

`merge_server_entry(existing: dict, name, command) -> dict` (pure): ensure
`mcpServers`, set `mcpServers["pf-helper"] = {"command": cmd[0], "args": cmd[1:]}`,
**preserving all other servers**. The register flow: read existing file (treat
missing as `{}`); if the file exists but is **malformed JSON, abort** (don't
overwrite); back up to `<file>.bak`; write merged JSON. Tell the user to restart
Desktop.

### Claude Code (`install/claude_code.py`)

Build argv `["claude", "mcp", "add", "pf-helper", "--", *server_command()]`. If
`shutil.which("claude")` is found, run it (inject the subprocess runner for
tests); else print the exact command to run. `--print` always just prints.

All path/merge/argv builders are pure functions; the filesystem and subprocess
edges are thin and injectable.

---

## Component 4 — Index handling & interactive setup

### `ensure_index` + ingest refactor

Refactor `ingest/build.py` so the build is callable as `run_ingest(cfg,
refresh=False)` (today's `main` becomes a thin wrapper that parses argv and calls
it). Add `ensure_index(cfg)` → if `cfg.db_path` is missing, run `run_ingest(cfg)`
with progress to **stderr**.

Per-command behavior:
- `setup` → `ensure_index` (after confirming the ~few-minute build).
- `bot` → `ensure_index` on launch (terminal process; progress to logs).
- `serve` → **does NOT build.** `server.main` checks `db_path` at startup; if
  missing, prints "No index — run `pf-helper setup`" to **stderr** and
  `sys.exit(1)`. (A multi-minute build would break Desktop's stdio MCP handshake,
  and build text on stdout would corrupt the JSON-RPC stream.)

### `setup` flow (interactive)

1. Resolve dirs; print where data/config will live.
2. If no index: prompt "Build the rules index now? (~a few minutes) [Y/n]" →
   `run_ingest`. (`--yes` skips prompts for non-interactive use.)
3. "Configure the Discord bot? [y/N]" → if yes, read the token with
   `getpass.getpass` (no echo) + optional guild id → `write_file_config` (0600).
   Token is never echoed or logged.
4. "Register the MCP server with which clients?" → desktop / claude-code /
   both / none → run the chosen `register` actions.
5. Print a summary + next steps (restart Desktop; how to run `pf-helper bot`).

Setup logic is factored into pure helpers (decision functions + actions) behind a
thin `input()`/`getpass` shell so the orchestration is testable.

---

## Component 5 — Discord token storage

Env var **and** config file (chosen over keyring/env-only). Precedence:
`DISCORD_BOT_TOKEN` env > `config.toml [discord] token`. The config file is in
the user config dir (outside the repo; repo `.gitignore` also covers any local
config), written with `chmod 600` on POSIX (Windows relies on user-profile
ACLs). The token is **never logged**. `BotConfig.from_env` is extended to fall
back to the config file when the env var is absent, and still raises a clear
error if neither provides a token.

---

## Component 6 — Documentation

Replace the Windows-MSIX-specific Desktop steps with one cross-platform guide:
install (`uv tool install .` or `pipx install .` from the clone) → `pf-helper
setup`. Keep a short "manual MCP config" appendix using `pf-helper print-config`.
Update `README.md`, `CLAUDE.md` (real commands), and fold the bot specifics from
`docs/discord-bot-setup.md` into the unified flow (token via `setup`).

---

## Dependencies

Add **`platformdirs`** to core `dependencies`. Everything else is stdlib:
`tomllib` (read), `argparse`, `getpass`, `shutil`, `subprocess`, `json`,
`pathlib`. No write-side TOML dependency (small built-in serializer for the few
keys we persist).

## File structure

```
pf_helper/
  cli.py            # NEW: argparse dispatcher; bare invocation -> serve
  __main__.py       # NEW: python -m pf_helper -> cli.main
  userconfig.py     # NEW: config path/dir resolution, load/write config.toml
  config.py         # MODIFY: data-dir resolution order; consult config file
  server.py         # MODIFY: startup db_path check -> stderr + exit(1) if missing
  ingest/build.py   # MODIFY: extract run_ingest(cfg, refresh); add ensure_index
  bot/config.py     # MODIFY: token/guild fall back to config file
  bot/main.py       # MODIFY: ensure_index on launch
  install/
    __init__.py
    server_cmd.py   # NEW: resolve server command
    desktop.py      # NEW: per-OS Desktop config path + merge entry
    claude_code.py  # NEW: claude mcp add argv + runner
pyproject.toml      # MODIFY: pf-helper -> cli:main; add platformdirs
docs/...            # MODIFY: cross-platform install/setup guide
tests/
  test_userconfig.py   # NEW
  test_cli.py          # NEW
  test_install.py      # NEW (desktop path/merge, server_cmd, claude_code argv)
  test_config.py       # MODIFY (data-dir resolution order)
  test_bot_embeds.py / test_answer_service.py  # MODIFY if config-file fallback touches them
```

## Error handling

- Desktop register: malformed existing JSON → abort (no overwrite); always back
  up before writing; Linux → clear "use Claude Code" message.
- Claude Code register: missing `claude` on PATH → print the command instead of
  failing.
- `serve` with no index → fast stderr error + exit 1 (never hang the handshake).
- Secrets: token read via `getpass`, stored 0600, never written to logs or
  printed (incl. `print-config`).
- `setup` is idempotent and re-runnable; `--yes` enables non-interactive runs.

## Testing

- **userconfig:** data-dir precedence (env > file > checkout > platformdirs, via
  monkeypatched env + a fake package root + injected base dirs); config
  load/merge/write round-trip; POSIX 0600 (skip/guard on Windows).
- **install/desktop:** per-OS path selection (monkeypatch `sys.platform`, env,
  tmp dirs incl. a fake MSIX `Claude_*` dir); `merge_server_entry` preserves
  other servers and is idempotent; malformed-JSON abort; backup written.
- **install/server_cmd:** resolution with `which` present vs absent
  (monkeypatched).
- **install/claude_code:** argv construction; runs vs prints based on injected
  `which`/runner.
- **cli:** dispatch routes each subcommand; bare invocation calls serve;
  `--print`/`--yes` honored. Inject fakes for the action functions.
- **server:** missing-index startup → SystemExit(1) + stderr message.
- **config/bot:** token/guild and data-dir fall back to the config file when env
  is absent; env still overrides.
- Gates: `uv run --no-sync pytest -q` green; `uv run --no-sync ruff check .`
  clean. (`uv sync` needed once to add `platformdirs` — Desktop must be quit, per
  the venv-lock gotcha.)

## Deferred / future

- **Phase 2 distribution:** PyPI/pipx publish; Docker image (wraps the same CLI).
- **OS keyring** token storage (`keyring`) as an opt-in hardening.
- **Prebuilt-index** download (`setup --from-release`) if first-run build time
  becomes a pain point.
- **Generic MCP-client** onboarding beyond `print-config`, if PF_Helper ever
  targets non-Anthropic clients.

# PF_Helper

A local [MCP](https://modelcontextprotocol.io) server that gives Claude fast,
accurate access to Pathfinder Second Edition rules, sourced from the
[FoundryVTT PF2e](https://github.com/foundryvtt/pf2e) compendium. Pure
retrieval — Claude reasons; this server searches.

## Requirements
- Python 3.14+
- [uv](https://docs.astral.sh/uv/)
- git
- Claude Desktop and/or Claude Code

## Install
```bash
uv sync
```

## Build the rules index (first run)
```bash
uv run pf-helper-ingest
```
This clones the FoundryVTT PF2e repo into `data/foundry-pf2e` (large; first
run takes a few minutes) and builds `data/pf2e.db`. Re-run anytime to update.

## Register with Claude Desktop
Add an `mcpServers` entry to `claude_desktop_config.json`. The most robust
option points directly at the console script created in this project's virtual
environment by `uv sync` — it needs no `cwd` and does not require `uv` to be on
Claude Desktop's PATH:
```json
{
  "mcpServers": {
    "pf-helper": {
      "command": "C:\\path\\to\\PF_Helper\\.venv\\Scripts\\pf-helper.exe"
    }
  }
}
```
Substitute your clone path. On macOS/Linux the script is
`/path/to/PF_Helper/.venv/bin/pf-helper`. The server locates its `data/pf2e.db`
index from its own package location, so no working directory is needed.

**Where is the config file?**
- Windows (.exe installer build): `%APPDATA%\Claude\claude_desktop_config.json`
- Windows (Microsoft Store / MSIX build): the app reads a *redirected* path,
  `%LOCALAPPDATA%\Packages\<PackageFamilyName>\LocalCache\Roaming\Claude\claude_desktop_config.json`.
  Find `<PackageFamilyName>` with PowerShell:
  `(Get-AppxPackage *Claude*).PackageFamilyName`. Editing the plain
  `%APPDATA%\Claude` path has **no effect** on the Store build.
- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`

Fully quit Claude Desktop (from the tray/menu bar, not just closing the window)
and reopen it; the `pf-helper` tools should appear.

**Why the direct `.exe` instead of `"command": "uv", "args": ["run", "pf-helper"]`?**
`uv run pf-helper` only resolves the script when it runs *inside* the project
directory, but Claude Desktop does not reliably apply the `cwd` field to the
spawned process — so `uv` fails with
`Failed to spawn: pf-helper: program not found`. The direct venv executable has
no such dependency. If you prefer `uv` (e.g. to auto-sync dependencies), make it
cwd-independent with `--directory`:
`"command": "uv"`, `"args": ["run", "--directory", "C:\\path\\to\\PF_Helper", "pf-helper"]`.

## Register with Claude Code
```bash
claude mcp add pf-helper -- uv run pf-helper
```
Run this from the project directory (so `uv` resolves this project), or add a
`.mcp.json` with the same command. Verify with `claude mcp list`.

## Verify
Ask Claude: "Using pf-helper, what does the frightened condition do?" Claude
should call `search`/`get_entry` and answer from the indexed text.

## Updating content
Re-run `uv run pf-helper-ingest` to pull the latest Foundry data and rebuild.

## Troubleshooting
- **"index not found" / empty results:** run `uv run pf-helper-ingest`.
- **`Failed to spawn: pf-helper: program not found` in the MCP log:** the server
  was launched via `uv run` without the project as its working directory. Use
  the direct `.venv\Scripts\pf-helper.exe` command shown above, or
  `uv run --directory <repo> pf-helper`.
- **Store/MSIX Claude Desktop ignores your config edits:** you likely edited
  `%APPDATA%\Claude\...`, but the Store build reads the redirected
  `%LOCALAPPDATA%\Packages\<PackageFamilyName>\LocalCache\Roaming\Claude\...`
  path (see "Where is the config file?" above).
- **Client doesn't list the server:** confirm the `command` path exists and runs
  in a terminal (it will block waiting on stdio — that means it launched; Ctrl-C
  to exit). The MCP log lives next to the config, under `...\Claude\logs\`.
- **Wrong Python:** `uv run python --version` should be 3.14+.

## Development
- Install dev tooling: `uv sync` (includes `ruff` and `pytest`).
- Run tests: `uv run pytest`
- Lint + format: `uv run ruff check .` and `uv run ruff format .`
- Architecture: an offline ingestion pipeline (`pf_helper/ingest/`) cleans the
  Foundry compendium into a SQLite + FTS5 index (`pf_helper/store/`); a
  `Retriever` interface (`pf_helper/retrieval/`) serves it; `pf_helper/server.py`
  exposes `search` and `get_entry` as MCP tools. See
  `docs/superpowers/specs/` for the full design.

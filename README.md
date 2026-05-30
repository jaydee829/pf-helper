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
Edit `claude_desktop_config.json`
(Windows: `%APPDATA%\Claude\claude_desktop_config.json`):
```json
{
  "mcpServers": {
    "pf-helper": {
      "command": "uv",
      "args": ["run", "pf-helper"],
      "cwd": "C:\\Users\\jayde\\Documents\\PF_Helper"
    }
  }
}
```
Set `cwd` to wherever you cloned this repo (the example uses this project's
path). Restart Claude Desktop; the `pf-helper` tools should appear.

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
- **Client doesn't list the server:** confirm `cwd` is the project root and
  `uv run pf-helper` works in a terminal.
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

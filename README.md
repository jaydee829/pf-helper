# PF_Helper

A local [MCP](https://modelcontextprotocol.io) server that gives Claude fast,
accurate access to Pathfinder Second Edition rules, sourced from the
[FoundryVTT PF2e](https://github.com/foundryvtt/pf2e) compendium. Pure
retrieval — Claude reasons; this server searches.

## Requirements
- Python 3.14+
- [uv](https://docs.astral.sh/uv/) or [pipx](https://pipx.pypa.io/)
- git
- Claude Desktop and/or Claude Code

## Install & setup (any OS)

1. Clone, then install the CLI:  `uv tool install .`  (or `pipx install .`)
2. Run setup:  `pf-helper setup`
   - builds the rules index (first run, ~a few minutes),
   - optionally stores your Discord bot token,
   - registers the MCP server with Claude Desktop and/or Claude Code.
3. Restart Claude Desktop. Run the bot with `pf-helper bot`.

Manual MCP config (other clients): `pf-helper print-config`.
Rebuild the index later: `pf-helper ingest --refresh` (quit Claude Desktop and stop the bot first — they hold the index DB open).

## Register with Claude Desktop
`pf-helper setup` handles this automatically. For manual setup, run:
```bash
pf-helper register --client desktop
```
Or print the JSON to paste manually:
```bash
pf-helper print-config
```

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
cwd-independent by passing the global `--directory` option before the `run`
subcommand:
```json
{
  "mcpServers": {
    "pf-helper": {
      "command": "uv",
      "args": ["--directory", "C:\\path\\to\\PF_Helper", "run", "pf-helper", "serve"]
    }
  }
}
```

## Register with Claude Code
```bash
pf-helper register --client claude-code
```
Or run it manually: `pf-helper register --client claude-code --print` to print
the `claude mcp add` command to run yourself. Verify with `claude mcp list`.

## Verify
Ask Claude: "Using pf-helper, what does the frightened condition do?" Claude
should call `search`/`get_entry` and answer from the indexed text.

## Updating content
Re-run `pf-helper ingest --refresh` to pull the latest Foundry data and rebuild.

## Troubleshooting
- **"index not found" / empty results:** run `pf-helper setup` (or `pf-helper ingest`).
- **`Failed to spawn: pf-helper: program not found` in the MCP log:** the server
  was launched via `uv run` without the project as its working directory. Use
  the direct `.venv\Scripts\pf-helper.exe` command shown above, or
  `uv --directory <repo> run pf-helper`.
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

## Discord bot (optional)

A Discord front-end with `/lookup`, `/search` (instant, local, no LLM), and
`/ask` (natural-language, powered by the Claude Agent SDK on your Claude
subscription — no API key). `/ask` answers are grounded in the index and cite
Archives of Nethys links; frequently-asked questions are cached.

### Install
```bash
uv sync --extra bot
```

### Choosing the /ask LLM provider

`/ask` defaults to your Claude subscription via the Claude Agent SDK. To use a
different provider, set `provider = "litellm"` (run `pf-helper setup` or edit
`config.toml`) and install the extra: `uv sync --extra bot --extra litellm`.

```toml
[ask]
provider = "litellm"
[ask.litellm]
model = "gemini/gemini-2.5-pro"   # or openai/gpt-4o, ollama/llama3.1, ...
# api_base = "http://localhost:11434/v1"   # local (Ollama/LM Studio)
```

Provider API keys come from that provider's standard env var
(`OPENAI_API_KEY`, `GEMINI_API_KEY`, ...) — PF_Helper never stores them. Local
models (Ollama) need no key.

### Prerequisites
- Build the index: `pf-helper ingest` (or let `pf-helper setup` do it).
- For `/ask`, authenticate Claude (uses your subscription, not an API key):
  `claude login` on a dev machine, or for a host run `claude setup-token` and
  export the resulting `CLAUDE_CODE_OAUTH_TOKEN`.
- A Discord bot token: Discord Developer Portal → your application → Bot → Reset
  Token. Invite the bot with OAuth2 scopes `bot` + `applications.commands`.

### Configure
Run `pf-helper setup` to store your Discord bot token interactively — it saves
it to the config file so you don't need to set it every session. Alternatively,
set the `DISCORD_BOT_TOKEN` environment variable directly.

| Var | Required | Purpose |
|---|---|---|
| `DISCORD_BOT_TOKEN` | yes (or use `pf-helper setup`) | Discord bot auth |
| `PF_HELPER_DISCORD_GUILD_ID` | no | register slash commands to one guild instantly (else global, ~1h to appear) |
| `PF_HELPER_DATA_DIR` | no | index location (default: repo `data/`) |
| `CLAUDE_CODE_OAUTH_TOKEN` | host only | subscription auth without interactive login |
| `PF_HELPER_ASK_ENGINE` | no | `auto` (default; agentic, falls back to single-shot) / `a` / `b` |
| `PF_HELPER_ASK_CACHE` | no | `1`/`0` — enable the /ask answer cache (default on) |

### Run
```bash
pf-helper bot
```
Then in your server: `/lookup Frightened`, `/search status penalty`,
`/ask How does flanking work?`. `/lookup` and `/search` never use your Claude
quota; `/ask` does (and degrades to suggesting `/lookup`·`/search` if Claude is
rate-limited).

### Notes
- Runs the same on your PC or an always-on host — only the environment differs.
- `/ask` needs Claude signed in; without it, `/ask` replies with a setup hint
  while `/lookup`·`/search` keep working.

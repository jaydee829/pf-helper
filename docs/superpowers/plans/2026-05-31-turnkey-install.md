# Turnkey Install & Multi-System Config Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make PF_Helper installable/configurable across Windows/macOS/Linux — a unified `pf-helper` CLI with a `setup` flow that builds the index, captures config, and registers the MCP server with Claude Desktop / Claude Code; user-scoped dirs + a config file when installed as a tool.

**Architecture:** Add a `userconfig` module (platformdirs dirs + `config.toml` load/write), an `install/` package (pure path/merge/argv builders for Desktop & Claude Code), an `argparse` CLI (`pf_helper/cli.py`) whose bare invocation still serves (back-compat), and a `setup_flow` orchestrator with injectable IO. Index build is refactored into a callable `run_ingest`/`ensure_index`.

**Tech Stack:** Python 3.14, `platformdirs` (new core dep), stdlib `tomllib`/`argparse`/`getpass`/`shutil`/`subprocess`/`json`, pytest (`uv run --no-sync pytest -q`), ruff (`uv run --no-sync ruff check .`).

**Spec:** `docs/superpowers/specs/2026-05-31-turnkey-install-design.md`

**⚠️ Execution prerequisite:** Task 1 runs `uv add platformdirs` and Task 11 changes a console-script entry point — both need `uv sync`, which fails if Claude Desktop is running (it locks `.venv\Scripts\pf-helper.exe`) or `pf-helper-ingest` is mid-build (it locks `data/pf2e.db`). **Before executing: quit Claude Desktop and ensure the ingest has finished.** After Task 1, use `uv run --no-sync` for all pytest/ruff.

**Conventions:** two separate `except` clauses (not `except (A, B):` — ruff py3.14 rewrites the tuple into a confusing comma form, unless there's an `as` binding); `from __future__ import annotations` at top of new modules; frozen dataclasses where the codebase already uses them.

---

### Task 1: `platformdirs` dep + `userconfig` module

**Files:**
- Modify: `pyproject.toml` (add dep)
- Create: `pf_helper/userconfig.py`
- Test: `tests/test_userconfig.py`

- [ ] **Step 1: Add the dependency**

Run: `uv add platformdirs` (requires Desktop quit). Confirm it lands in `[project] dependencies` in `pyproject.toml` alongside `mcp[cli]`, `beautifulsoup4`.

- [ ] **Step 2: Write failing tests** — create `tests/test_userconfig.py`:

```python
import pf_helper.userconfig as uc


def test_data_dir_default_prefers_source_checkout(tmp_path, monkeypatch):
    # a fake package dir whose parent HAS pyproject.toml -> repo/data
    pkg = tmp_path / "repo" / "pf_helper"
    pkg.mkdir(parents=True)
    (tmp_path / "repo" / "pyproject.toml").write_text("x")
    assert uc.data_dir_default(package_file=str(pkg / "userconfig.py")) == tmp_path / "repo" / "data"


def test_data_dir_default_falls_back_to_platformdirs(tmp_path, monkeypatch):
    pkg = tmp_path / "site" / "pf_helper"
    pkg.mkdir(parents=True)  # no pyproject.toml at parent
    monkeypatch.setattr(uc.platformdirs, "user_data_dir", lambda app: str(tmp_path / "udd" / app))
    assert uc.data_dir_default(package_file=str(pkg / "userconfig.py")) == tmp_path / "udd" / "pf-helper"


def test_config_path_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("PF_HELPER_CONFIG", str(tmp_path / "c.toml"))
    assert uc.config_path() == tmp_path / "c.toml"


def test_load_missing_returns_empty(tmp_path):
    assert uc.load_file_config(tmp_path / "nope.toml") == {}


def test_write_then_load_roundtrip_with_windows_path(tmp_path):
    p = tmp_path / "config.toml"
    uc.write_file_config({"data_dir": r"C:\Users\x\data", "discord": {"token": "abc.def", "guild_id": 123}}, path=p)
    cfg = uc.load_file_config(p)
    assert cfg["data_dir"] == r"C:\Users\x\data"  # backslashes survive (literal string)
    assert cfg["discord"] == {"token": "abc.def", "guild_id": 123}


def test_write_merges_not_clobbers(tmp_path):
    p = tmp_path / "config.toml"
    uc.write_file_config({"discord": {"token": "t1"}}, path=p)
    uc.write_file_config({"discord": {"guild_id": 9}}, path=p)
    cfg = uc.load_file_config(p)
    assert cfg["discord"] == {"token": "t1", "guild_id": 9}
```

- [ ] **Step 3: Run** `uv run --no-sync pytest tests/test_userconfig.py -v` — expect FAIL (module missing).

- [ ] **Step 4: Implement** `pf_helper/userconfig.py`:

```python
"""User-scoped paths + config.toml load/write (layer below env vars)."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

import platformdirs

_APP = "pf-helper"


def config_path() -> Path:
    override = os.environ.get("PF_HELPER_CONFIG")
    if override:
        return Path(override)
    return Path(platformdirs.user_config_dir(_APP)) / "config.toml"


def data_dir_default(package_file: str | None = None) -> Path:
    pkg = Path(package_file or __file__).resolve()
    repo_root = pkg.parent.parent  # <repo>/pf_helper/userconfig.py -> <repo>
    if (repo_root / "pyproject.toml").exists():
        return repo_root / "data"  # source checkout: preserve dev behavior
    return Path(platformdirs.user_data_dir(_APP))


def load_file_config(path: Path | None = None) -> dict:
    p = path or config_path()
    if not p.exists():
        return {}
    try:
        with p.open("rb") as f:
            return tomllib.load(f)
    except OSError:
        return {}
    except tomllib.TOMLDecodeError:
        return {}


def _deep_merge(base: dict, updates: dict) -> dict:
    out = dict(base)
    for k, v in updates.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _toml_scalar(v: object) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return repr(v)
    s = str(v)
    if "'" in s:  # fall back to a basic string with escapes
        return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return "'" + s + "'"  # literal string: backslashes (Windows paths) survive verbatim


def _dumps(cfg: dict) -> str:
    lines = [f"{k} = {_toml_scalar(v)}" for k, v in cfg.items() if not isinstance(v, dict)]
    for k, v in cfg.items():
        if isinstance(v, dict):
            lines.append(f"\n[{k}]")
            lines += [f"{kk} = {_toml_scalar(vv)}" for kk, vv in v.items()]
    return "\n".join(lines) + "\n"


def write_file_config(updates: dict, path: Path | None = None) -> Path:
    p = path or config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    merged = _deep_merge(load_file_config(p), updates)
    p.write_text(_dumps(merged), encoding="utf-8")
    if os.name == "posix":
        p.chmod(0o600)
    return p
```

- [ ] **Step 5: Run** `uv run --no-sync pytest tests/test_userconfig.py -q` — expect PASS. Then `uv run --no-sync ruff check pf_helper/userconfig.py tests/test_userconfig.py`.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock pf_helper/userconfig.py tests/test_userconfig.py
git commit -m "feat: platformdirs dep + userconfig (paths + config.toml)"
```

---

### Task 2: `Config` data-dir resolution consults the config file

**Files:**
- Modify: `pf_helper/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write failing tests** — append to `tests/test_config.py`:

```python
import pf_helper.config as cfgmod


def test_from_env_prefers_env(tmp_path, monkeypatch):
    monkeypatch.setenv("PF_HELPER_DATA_DIR", str(tmp_path / "envdata"))
    monkeypatch.setattr(cfgmod.userconfig, "load_file_config", lambda: {"data_dir": str(tmp_path / "filedata")})
    assert cfgmod.Config.from_env().data_dir == tmp_path / "envdata"


def test_from_env_uses_config_file_when_no_env(tmp_path, monkeypatch):
    monkeypatch.delenv("PF_HELPER_DATA_DIR", raising=False)
    monkeypatch.setattr(cfgmod.userconfig, "load_file_config", lambda: {"data_dir": str(tmp_path / "filedata")})
    assert cfgmod.Config.from_env().data_dir == tmp_path / "filedata"


def test_from_env_falls_back_to_default(monkeypatch):
    monkeypatch.delenv("PF_HELPER_DATA_DIR", raising=False)
    monkeypatch.setattr(cfgmod.userconfig, "load_file_config", dict)
    monkeypatch.setattr(cfgmod.userconfig, "data_dir_default", lambda: __import__("pathlib").Path("/tmp/dd"))
    assert cfgmod.Config.from_env().data_dir == __import__("pathlib").Path("/tmp/dd")
```

- [ ] **Step 2: Run** `uv run --no-sync pytest tests/test_config.py -v` — expect FAIL (`Config` doesn't reference `userconfig`).

- [ ] **Step 3: Implement** — in `pf_helper/config.py`, add the import and rewrite `from_env`:

```python
from pf_helper import userconfig
```

Replace the existing `from_env` classmethod body with:

```python
    @classmethod
    def from_env(cls) -> Config:
        file_cfg = userconfig.load_file_config()
        data = os.environ.get("PF_HELPER_DATA_DIR") or file_cfg.get("data_dir")
        data_dir = Path(data) if data else userconfig.data_dir_default()
        return cls(data_dir=data_dir)
```

(Leave the `_DEFAULT_DATA` module constant and the `data_dir` field default as-is for bare `Config()` construction.)

- [ ] **Step 4: Run** `uv run --no-sync pytest tests/test_config.py -q` — expect PASS. Run the whole suite `uv run --no-sync pytest -q` to confirm nothing regressed (from a source checkout, `data_dir_default()` resolves to `<repo>/data`, matching prior behavior). Then ruff.

- [ ] **Step 5: Commit**

```bash
git add pf_helper/config.py tests/test_config.py
git commit -m "feat: Config.from_env resolves data dir via env > file > default"
```

---

### Task 3: `install/server_cmd.py` — resolve the server command

**Files:**
- Create: `pf_helper/install/__init__.py` (empty), `pf_helper/install/server_cmd.py`
- Test: `tests/test_install.py`

- [ ] **Step 1: Write failing tests** — create `tests/test_install.py`:

```python
import sys

from pf_helper.install.server_cmd import server_command


def test_server_command_prefers_installed_script():
    assert server_command(which=lambda n: "/usr/bin/pf-helper") == ["/usr/bin/pf-helper", "serve"]


def test_server_command_falls_back_to_module():
    assert server_command(which=lambda n: None) == [sys.executable, "-m", "pf_helper", "serve"]
```

- [ ] **Step 2: Run** `uv run --no-sync pytest tests/test_install.py -v` — expect FAIL.

- [ ] **Step 3: Implement** — `pf_helper/install/__init__.py` (empty file) and `pf_helper/install/server_cmd.py`:

```python
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
```

- [ ] **Step 4: Run** `uv run --no-sync pytest tests/test_install.py -q` — expect PASS. Then ruff.

- [ ] **Step 5: Commit**

```bash
git add pf_helper/install/__init__.py pf_helper/install/server_cmd.py tests/test_install.py
git commit -m "feat: resolve MCP server command for registration"
```

---

### Task 4: `install/desktop.py` — per-OS path + merge + register

**Files:**
- Create: `pf_helper/install/desktop.py`
- Test: `tests/test_install.py` (extend)

- [ ] **Step 1: Write failing tests** — append to `tests/test_install.py`:

```python
import json
from pathlib import Path

import pytest

from pf_helper.install import desktop


def test_desktop_path_macos(tmp_path):
    p = desktop.desktop_config_path(platform="darwin", env={"HOME": str(tmp_path)})
    assert p == tmp_path / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"


def test_desktop_path_windows_msix_glob(tmp_path):
    local = tmp_path / "Local"
    msix = local / "Packages" / "Claude_abc123" / "LocalCache" / "Roaming" / "Claude"
    msix.mkdir(parents=True)
    (msix / "claude_desktop_config.json").write_text("{}")
    p = desktop.desktop_config_path(platform="win32", env={"LOCALAPPDATA": str(local), "APPDATA": str(tmp_path / "Roaming")})
    assert p == msix / "claude_desktop_config.json"


def test_desktop_path_windows_appdata_fallback(tmp_path):
    p = desktop.desktop_config_path(platform="win32", env={"LOCALAPPDATA": str(tmp_path / "none"), "APPDATA": str(tmp_path / "Roaming")})
    assert p == tmp_path / "Roaming" / "Claude" / "claude_desktop_config.json"


def test_desktop_path_linux_is_none():
    assert desktop.desktop_config_path(platform="linux", env={"HOME": "/home/x"}) is None


def test_merge_preserves_other_servers():
    existing = {"mcpServers": {"other": {"command": "x"}}}
    out = desktop.merge_server_entry(existing, ["pf", "serve"])
    assert out["mcpServers"]["other"] == {"command": "x"}
    assert out["mcpServers"]["pf-helper"] == {"command": "pf", "args": ["serve"]}


def test_register_desktop_backs_up_and_merges(tmp_path):
    cfg = tmp_path / "claude_desktop_config.json"
    cfg.write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}}))
    desktop.register_desktop(["pf", "serve"], path=cfg)
    data = json.loads(cfg.read_text())
    assert "other" in data["mcpServers"] and "pf-helper" in data["mcpServers"]
    assert (tmp_path / "claude_desktop_config.json.bak").exists()


def test_register_desktop_aborts_on_malformed(tmp_path):
    cfg = tmp_path / "claude_desktop_config.json"
    cfg.write_text("{not json")
    with pytest.raises(RuntimeError, match="not valid JSON"):
        desktop.register_desktop(["pf", "serve"], path=cfg)


def test_register_desktop_creates_when_absent(tmp_path):
    cfg = tmp_path / "sub" / "claude_desktop_config.json"
    desktop.register_desktop(["pf", "serve"], path=cfg)
    assert json.loads(cfg.read_text())["mcpServers"]["pf-helper"]["command"] == "pf"
```

- [ ] **Step 2: Run** `uv run --no-sync pytest tests/test_install.py -k desktop -v` — expect FAIL.

- [ ] **Step 3: Implement** — `pf_helper/install/desktop.py`:

```python
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
        raise RuntimeError("Claude Desktop isn't available on this OS — use `--client claude-code`.")
    if p.exists():
        try:
            existing = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"{p} is not valid JSON; refusing to overwrite.") from exc
        backup = p.with_suffix(p.suffix + ".bak")
        backup.write_text(json.dumps(existing, indent=2), encoding="utf-8")
    else:
        existing = {}
        p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(merge_server_entry(existing, command), indent=2), encoding="utf-8")
    return p
```

- [ ] **Step 4: Run** `uv run --no-sync pytest tests/test_install.py -q` — expect PASS. Then ruff.

- [ ] **Step 5: Commit**

```bash
git add pf_helper/install/desktop.py tests/test_install.py
git commit -m "feat: cross-platform Claude Desktop MCP registration"
```

---

### Task 5: `install/claude_code.py` — argv + runner

**Files:**
- Create: `pf_helper/install/claude_code.py`
- Test: `tests/test_install.py` (extend)

- [ ] **Step 1: Write failing tests** — append to `tests/test_install.py`:

```python
from pf_helper.install import claude_code


def test_claude_code_argv():
    assert claude_code.claude_code_argv(["pf", "serve"]) == [
        "claude", "mcp", "add", "pf-helper", "--", "pf", "serve"
    ]


def test_register_claude_code_runs_when_present():
    calls = []
    ok = claude_code.register_claude_code(
        ["pf", "serve"], which=lambda n: "/usr/bin/claude", run=lambda argv, check: calls.append(argv)
    )
    assert ok is True and calls == [["claude", "mcp", "add", "pf-helper", "--", "pf", "serve"]]


def test_register_claude_code_skips_when_absent():
    ok = claude_code.register_claude_code(
        ["pf", "serve"], which=lambda n: None, run=lambda *a, **k: (_ for _ in ()).throw(AssertionError)
    )
    assert ok is False
```

- [ ] **Step 2: Run** `uv run --no-sync pytest tests/test_install.py -k claude_code -v` — expect FAIL.

- [ ] **Step 3: Implement** — `pf_helper/install/claude_code.py`:

```python
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
```

- [ ] **Step 4: Run** `uv run --no-sync pytest tests/test_install.py -q` — expect PASS. Then ruff.

- [ ] **Step 5: Commit**

```bash
git add pf_helper/install/claude_code.py tests/test_install.py
git commit -m "feat: Claude Code MCP registration"
```

---

### Task 6: Refactor ingest into `run_ingest` + `ensure_index`

**Files:**
- Modify: `pf_helper/ingest/build.py`
- Test: `tests/test_build.py` (extend)

- [ ] **Step 1: Write failing tests** — append to `tests/test_build.py`:

```python
import pf_helper.ingest.build as build
from pf_helper.config import Config


def test_ensure_index_builds_when_missing(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(build, "run_ingest", lambda cfg, refresh=False: calls.append(cfg))
    cfg = Config(data_dir=tmp_path)  # no pf2e.db present
    build.ensure_index(cfg)
    assert calls == [cfg]


def test_ensure_index_skips_when_present(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(build, "run_ingest", lambda cfg, refresh=False: calls.append(cfg))
    cfg = Config(data_dir=tmp_path)
    cfg.db_path.write_text("db")  # index already there
    build.ensure_index(cfg)
    assert calls == []
```

- [ ] **Step 2: Run** `uv run --no-sync pytest tests/test_build.py -k ensure_index -v` — expect FAIL.

- [ ] **Step 3: Implement** — in `pf_helper/ingest/build.py`:

3a. Rename the existing `main()` body: define `run_ingest(cfg: Config, refresh: bool = False) -> None` containing everything `main` currently does **after** computing `refresh` (the `_ensure_foundry_repo` / `_ensure_aon_cache` / link cache / `build_index` / print steps), using the passed-in `cfg` and `refresh` instead of creating its own.

3b. Add:

```python
def ensure_index(cfg: Config) -> None:
    """Build the index if it doesn't exist yet (used by setup and the bot)."""
    from pathlib import Path

    if not Path(cfg.db_path).exists():
        run_ingest(cfg)
```

3c. Make `main` a thin wrapper:

```python
def main() -> None:
    refresh = "--refresh" in sys.argv[1:]
    run_ingest(Config.from_env(), refresh=refresh)
```

(Keep all existing helper functions and imports. `sys` and `Config` are already imported.)

- [ ] **Step 4: Run** `uv run --no-sync pytest tests/test_build.py -q` — expect PASS. Then ruff.

- [ ] **Step 5: Commit**

```bash
git add pf_helper/ingest/build.py tests/test_build.py
git commit -m "refactor: extract run_ingest + ensure_index from build.main"
```

---

### Task 7: `serve` fast-errors when the index is missing

**Files:**
- Modify: `pf_helper/server.py`
- Test: `tests/test_server.py` (extend)

- [ ] **Step 1: Write failing tests** — append to `tests/test_server.py`:

```python
import pytest

import pf_helper.server as server
from pf_helper.config import Config


def test_require_index_exits_when_missing(tmp_path, capsys):
    with pytest.raises(SystemExit) as ei:
        server._require_index(Config(data_dir=tmp_path))
    assert ei.value.code == 1
    assert "setup" in capsys.readouterr().err


def test_require_index_passes_when_present(tmp_path):
    cfg = Config(data_dir=tmp_path)
    cfg.db_path.write_text("db")
    server._require_index(cfg)  # no raise
```

- [ ] **Step 2: Run** `uv run --no-sync pytest tests/test_server.py -k require_index -v` — expect FAIL.

- [ ] **Step 3: Implement** — in `pf_helper/server.py`, add `import sys` (if absent) and:

```python
def _require_index(cfg: Config) -> None:
    if not Path(cfg.db_path).exists():
        print(
            f"No rules index at {cfg.db_path} — run `pf-helper setup` (or `pf-helper ingest`).",
            file=sys.stderr,
        )
        raise SystemExit(1)
```

Update `main` to call it:

```python
def main() -> None:
    cfg = Config.from_env()
    _require_index(cfg)
    configure(cfg)
    mcp.run()  # stdio transport by default
```

- [ ] **Step 4: Run** `uv run --no-sync pytest tests/test_server.py -q` — expect PASS. Then ruff.

- [ ] **Step 5: Commit**

```bash
git add pf_helper/server.py tests/test_server.py
git commit -m "feat: serve exits with guidance when index is missing"
```

---

### Task 8: Bot reads token/guild from config file + auto-builds index

**Files:**
- Modify: `pf_helper/bot/config.py`, `pf_helper/bot/main.py`
- Test: `tests/test_bot_embeds.py` (extend) or a new `tests/test_bot_config.py`

- [ ] **Step 1: Write failing tests** — create `tests/test_bot_config.py`:

```python
import pytest

import pf_helper.bot.config as botcfg
from pf_helper.bot.config import BotConfig


def test_token_from_env_wins(monkeypatch):
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "envtok")
    monkeypatch.setattr(botcfg.userconfig, "load_file_config", lambda: {"discord": {"token": "filetok"}})
    assert BotConfig.from_env().token == "envtok"


def test_token_from_config_file(monkeypatch):
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
    monkeypatch.setattr(
        botcfg.userconfig, "load_file_config", lambda: {"discord": {"token": "filetok", "guild_id": 7}}
    )
    cfg = BotConfig.from_env()
    assert cfg.token == "filetok" and cfg.guild_id == 7


def test_missing_token_raises(monkeypatch):
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
    monkeypatch.setattr(botcfg.userconfig, "load_file_config", dict)
    with pytest.raises(ValueError, match="DISCORD_BOT_TOKEN"):
        BotConfig.from_env()
```

- [ ] **Step 2: Run** `uv run --no-sync pytest tests/test_bot_config.py -v` — expect FAIL.

- [ ] **Step 3: Implement** — rewrite `pf_helper/bot/config.py`:

```python
"""Discord-bot configuration from env vars, falling back to config.toml."""

from __future__ import annotations

import os
from dataclasses import dataclass

from pf_helper import userconfig


@dataclass(frozen=True)
class BotConfig:
    token: str
    guild_id: int | None = None

    @classmethod
    def from_env(cls) -> BotConfig:
        disc = userconfig.load_file_config().get("discord", {})
        token = os.environ.get("DISCORD_BOT_TOKEN") or disc.get("token")
        if not token:
            raise ValueError("DISCORD_BOT_TOKEN is required to run the bot (env or config.toml)")
        gid_env = os.environ.get("PF_HELPER_DISCORD_GUILD_ID")
        gid = gid_env if gid_env else disc.get("guild_id")
        return cls(token=str(token), guild_id=int(gid) if gid else None)
```

3b. In `pf_helper/bot/main.py`, build the index on launch. Add the import and call at the top of `main()`:

```python
from pf_helper.ingest.build import ensure_index
```

In `main()`, after `answer_cfg = AnswerConfig.from_env()` and before `build_bot(...)`:

```python
    ensure_index(answer_cfg.core)
```

- [ ] **Step 4: Run** `uv run --no-sync pytest tests/test_bot_config.py -q` and the whole suite `uv run --no-sync pytest -q` — expect PASS. Then ruff.

- [ ] **Step 5: Commit**

```bash
git add pf_helper/bot/config.py pf_helper/bot/main.py tests/test_bot_config.py
git commit -m "feat: bot token/guild from config file + auto-build index on launch"
```

---

### Task 9: `pf-helper` CLI dispatcher (serve/bot/ingest/register/print-config) + `__main__`

**Files:**
- Create: `pf_helper/cli.py`, `pf_helper/__main__.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write failing tests** — create `tests/test_cli.py`:

```python
import pf_helper.cli as cli


def test_bare_invocation_serves(monkeypatch):
    called = []
    monkeypatch.setattr(cli, "_cmd_serve", lambda args: called.append("serve"))
    cli.main([])
    assert called == ["serve"]


def test_ingest_passes_refresh(monkeypatch):
    seen = {}
    import pf_helper.ingest.build as build
    monkeypatch.setattr(build, "run_ingest", lambda cfg, refresh=False: seen.update(refresh=refresh))
    import pf_helper.config as cfgmod
    monkeypatch.setattr(cfgmod.Config, "from_env", classmethod(lambda cls: cls()))
    cli.main(["ingest", "--refresh"])
    assert seen == {"refresh": True}


def test_register_desktop_routes(monkeypatch):
    from pf_helper.install import desktop, server_cmd
    monkeypatch.setattr(server_cmd, "server_command", lambda: ["pf", "serve"])
    seen = {}
    monkeypatch.setattr(desktop, "register_desktop", lambda cmd: seen.setdefault("cmd", cmd) or __import__("pathlib").Path("/x"))
    cli.main(["register", "--client", "desktop"])
    assert seen["cmd"] == ["pf", "serve"]


def test_print_config_outputs_json(monkeypatch, capsys):
    from pf_helper.install import server_cmd
    monkeypatch.setattr(server_cmd, "server_command", lambda: ["pf", "serve"])
    cli.main(["print-config"])
    out = capsys.readouterr().out
    assert "pf-helper" in out and "serve" in out
```

- [ ] **Step 2: Run** `uv run --no-sync pytest tests/test_cli.py -v` — expect FAIL.

- [ ] **Step 3: Implement** — `pf_helper/cli.py`:

```python
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
    reg.add_argument("--print", dest="print_only", action="store_true", help="Print config instead of writing")
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
```

`pf_helper/__main__.py`:

```python
from pf_helper.cli import main

main()
```

- [ ] **Step 4: Run** `uv run --no-sync pytest tests/test_cli.py -q` — expect PASS. Then ruff.

- [ ] **Step 5: Commit**

```bash
git add pf_helper/cli.py pf_helper/__main__.py tests/test_cli.py
git commit -m "feat: unified pf-helper CLI (bare -> serve) + python -m entry"
```

---

### Task 10: Interactive `setup` flow

**Files:**
- Create: `pf_helper/setup_flow.py`
- Test: `tests/test_setup_flow.py`

- [ ] **Step 1: Write failing tests** — create `tests/test_setup_flow.py`:

```python
from pathlib import Path

import pf_helper.setup_flow as sf
from pf_helper.config import Config


def _fake_inputs(answers):
    it = iter(answers)
    return lambda prompt="": next(it)


def test_setup_builds_index_saves_token_registers(tmp_path, monkeypatch):
    cfg = Config(data_dir=tmp_path)  # no db -> build path
    monkeypatch.setattr(sf.Config, "from_env", classmethod(lambda cls: cfg))
    built, written, registered = [], [], []
    monkeypatch.setattr(sf, "ensure_index", lambda c: built.append(c))
    monkeypatch.setattr(sf.userconfig, "write_file_config", lambda updates: written.append(updates) or Path("x"))
    monkeypatch.setattr(sf, "server_command", lambda: ["pf", "serve"])
    monkeypatch.setattr(sf.desktop, "register_desktop", lambda cmd: registered.append(("desktop", cmd)) or Path("d"))
    monkeypatch.setattr(sf.claude_code, "register_claude_code", lambda cmd: registered.append(("cc", cmd)) or True)

    # answers: build index? y | configure bot? y | guild id "" | register desktop? y | claude-code? y
    sf.run_setup(
        input_fn=_fake_inputs(["y", "y", "", "y", "y"]),
        getpass_fn=lambda prompt="": "secrettok",
    )
    assert built == [cfg]
    assert written == [{"discord": {"token": "secrettok"}}]
    assert ("desktop", ["pf", "serve"]) in registered and ("cc", ["pf", "serve"]) in registered


def test_setup_yes_builds_only(tmp_path, monkeypatch):
    cfg = Config(data_dir=tmp_path)
    monkeypatch.setattr(sf.Config, "from_env", classmethod(lambda cls: cfg))
    built, written = [], []
    monkeypatch.setattr(sf, "ensure_index", lambda c: built.append(c))
    monkeypatch.setattr(sf.userconfig, "write_file_config", lambda updates: written.append(updates))
    sf.run_setup(yes=True)
    assert built == [cfg] and written == []
```

- [ ] **Step 2: Run** `uv run --no-sync pytest tests/test_setup_flow.py -v` — expect FAIL.

- [ ] **Step 3: Implement** — `pf_helper/setup_flow.py`:

```python
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

    if not cfg.db_path.exists() and (yes or _yn(input_fn, "Build the rules index now? (~a few minutes)", default=True)):
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
```

- [ ] **Step 4: Run** `uv run --no-sync pytest tests/test_setup_flow.py -q` — expect PASS. Then ruff.

- [ ] **Step 5: Commit**

```bash
git add pf_helper/setup_flow.py tests/test_setup_flow.py
git commit -m "feat: interactive pf-helper setup flow"
```

---

### Task 11: Entry-point switch + docs

**Files:**
- Modify: `pyproject.toml`, `README.md`, `CLAUDE.md`, `docs/discord-bot-setup.md`

- [ ] **Step 1: Switch the console script** — in `pyproject.toml` `[project.scripts]`, change:

```toml
pf-helper = "pf_helper.cli:main"
```

(Leave `pf-helper-ingest` and `pf-helper-bot` as-is.) Re-sync so the regenerated `pf-helper` script points at the CLI: run `uv sync` (requires Desktop quit). Verify the new dispatcher resolves: `uv run --no-sync pf-helper print-config` prints JSON, and `uv run --no-sync pf-helper --help` lists the subcommands. (Don't run bare `pf-helper` to verify here — with an index present it will start the stdio server and block; the bare→serve routing is unit-tested in Task 9 and the no-index exit in Task 7.)

- [ ] **Step 2: Docs** — replace the Windows-MSIX-specific Desktop instructions with a cross-platform quickstart. In `README.md` add an "Install & setup" section:

```markdown
## Install & setup (any OS)

1. Clone, then install the CLI:  `uv tool install .`  (or `pipx install .`)
2. Run setup:  `pf-helper setup`
   - builds the rules index (first run, ~a few minutes),
   - optionally stores your Discord bot token,
   - registers the MCP server with Claude Desktop and/or Claude Code.
3. Restart Claude Desktop. Run the bot with `pf-helper bot`.

Manual MCP config (other clients): `pf-helper print-config`.
Rebuild the index later: `pf-helper ingest --refresh` (quit Desktop/bot first — they hold the DB open).
```

Update `CLAUDE.md` build/run commands to the `pf-helper <subcommand>` forms. In `docs/discord-bot-setup.md`, replace the manual token-env steps with "run `pf-helper setup` and choose to configure the bot" (keep the Discord developer-portal/bot-invite steps).

- [ ] **Step 3: Full gate** — `uv run --no-sync pytest -q` (all green) and `uv run --no-sync ruff check .` (clean).

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock README.md CLAUDE.md docs/discord-bot-setup.md
git commit -m "feat: pf-helper CLI entry point + cross-platform setup docs"
```

---

## Final verification (after all tasks)

- [ ] `uv run --no-sync pytest -q` — full suite green.
- [ ] `uv run --no-sync ruff check .` — clean.
- [ ] `uv run --no-sync pf-helper --help` lists subcommands; bare→serve routing covered by Task 9's unit test (don't run bare here — with an index it starts the blocking stdio server).
- [ ] `uv run --no-sync pf-helper print-config` → valid MCP JSON with the resolved command.
- [ ] `uv run --no-sync pf-helper register --client desktop --print` → JSON snippet; `--client claude-code --print` → the `claude mcp add …` line.
- [ ] Open PR (do not merge); then retrieve + address Gemini review comments per the project workflow.

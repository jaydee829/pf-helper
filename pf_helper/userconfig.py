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

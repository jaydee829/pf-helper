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
    # TOML has no null; omit None values (a "None" literal would load back as a string).
    lines = [
        f"{k} = {_toml_scalar(v)}"
        for k, v in cfg.items()
        if not isinstance(v, dict) and v is not None
    ]
    for k, v in cfg.items():
        if isinstance(v, dict):
            section = [f"{kk} = {_toml_scalar(vv)}" for kk, vv in v.items() if vv is not None]
            if section:
                lines.append(f"\n[{k}]")
                lines += section
    return "\n".join(lines) + "\n"


def write_file_config(updates: dict, path: Path | None = None) -> Path:
    p = path or config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    content = _dumps(_deep_merge(load_file_config(p), updates))
    if os.name == "posix":
        # Create with 0o600 from the start so the token is never briefly world-readable.
        fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        p.chmod(0o600)  # also tighten an already-existing file with looser perms
    else:
        p.write_text(content, encoding="utf-8")
    return p

import json
import sys

import pytest

from pf_helper.install import desktop
from pf_helper.install.server_cmd import server_command


def test_server_command_prefers_installed_script():
    assert server_command(which=lambda n: "/usr/bin/pf-helper") == ["/usr/bin/pf-helper", "serve"]


def test_server_command_falls_back_to_module():
    assert server_command(which=lambda n: None) == [sys.executable, "-m", "pf_helper", "serve"]


def test_desktop_path_macos(tmp_path):
    p = desktop.desktop_config_path(platform="darwin", env={"HOME": str(tmp_path)})
    expected = (
        tmp_path / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    )
    assert p == expected


def test_desktop_path_windows_msix_glob(tmp_path):
    local = tmp_path / "Local"
    msix = local / "Packages" / "Claude_abc123" / "LocalCache" / "Roaming" / "Claude"
    msix.mkdir(parents=True)
    (msix / "claude_desktop_config.json").write_text("{}")
    p = desktop.desktop_config_path(
        platform="win32", env={"LOCALAPPDATA": str(local), "APPDATA": str(tmp_path / "Roaming")}
    )
    assert p == msix / "claude_desktop_config.json"


def test_desktop_path_windows_appdata_fallback(tmp_path):
    p = desktop.desktop_config_path(
        platform="win32",
        env={"LOCALAPPDATA": str(tmp_path / "none"), "APPDATA": str(tmp_path / "Roaming")},
    )
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

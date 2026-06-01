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
    monkeypatch.setattr(
        sf.userconfig,
        "write_file_config",
        lambda updates: written.append(updates) or Path("x"),
    )
    monkeypatch.setattr(sf, "server_command", lambda: ["pf", "serve"])
    monkeypatch.setattr(
        sf.desktop,
        "register_desktop",
        lambda cmd: registered.append(("desktop", cmd)) or Path("d"),
    )
    monkeypatch.setattr(
        sf.claude_code,
        "register_claude_code",
        lambda cmd: registered.append(("cc", cmd)) or True,
    )

    # answers: build index? y | configure bot? y | guild id ""
    # provider? n | register desktop? y | claude-code? y
    sf.run_setup(
        input_fn=_fake_inputs(["y", "y", "", "n", "y", "y"]),
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


def test_setup_reprompts_on_invalid_guild_id(tmp_path, monkeypatch):
    cfg = Config(data_dir=tmp_path)
    cfg.db_path.write_text("db")  # index present -> skip build prompt
    monkeypatch.setattr(sf.Config, "from_env", classmethod(lambda cls: cfg))
    written = []
    monkeypatch.setattr(sf.userconfig, "write_file_config", lambda updates: written.append(updates))
    monkeypatch.setattr(sf, "server_command", lambda: ["pf", "serve"])
    # configure bot? y | guild "abc" (invalid) | guild "42" | provider? n | desktop? n | cc? n
    sf.run_setup(
        input_fn=_fake_inputs(["y", "abc", "42", "n", "n", "n"]),
        getpass_fn=lambda prompt="": "tok",
    )
    assert written == [{"discord": {"token": "tok", "guild_id": 42}}]


def test_setup_claude_code_failure_is_graceful(tmp_path, monkeypatch, capsys):
    import subprocess

    cfg = Config(data_dir=tmp_path)
    cfg.db_path.write_text("db")
    monkeypatch.setattr(sf.Config, "from_env", classmethod(lambda cls: cfg))
    monkeypatch.setattr(sf, "server_command", lambda: ["pf", "serve"])

    def boom(cmd):
        raise subprocess.CalledProcessError(1, "claude")

    monkeypatch.setattr(sf.claude_code, "register_claude_code", boom)
    # configure bot? n | provider? n | desktop? n | claude-code? y  (should NOT raise)
    sf.run_setup(input_fn=_fake_inputs(["n", "n", "n", "y"]))
    out = capsys.readouterr().out
    assert "Failed to register with Claude Code" in out and "claude mcp add" in out


def test_setup_configures_litellm_provider(tmp_path, monkeypatch):
    cfg = Config(data_dir=tmp_path)
    cfg.db_path.write_text("db")  # skip build prompt
    monkeypatch.setattr(sf.Config, "from_env", classmethod(lambda cls: cfg))
    written = []
    monkeypatch.setattr(sf.userconfig, "write_file_config", lambda updates: written.append(updates))
    monkeypatch.setattr(sf, "server_command", lambda: ["pf", "serve"])
    # bot? n | provider? y | provider=litellm | model | api_base "" | desktop? n | cc? n
    sf.run_setup(
        input_fn=_fake_inputs(["n", "y", "litellm", "ollama/llama3.1", "", "n", "n"]),
        getpass_fn=lambda prompt="": "",
    )
    assert {"ask": {"provider": "litellm", "litellm": {"model": "ollama/llama3.1"}}} in written


def test_setup_provider_claude_sdk_writes_provider_only(tmp_path, monkeypatch):
    cfg = Config(data_dir=tmp_path)
    cfg.db_path.write_text("db")
    monkeypatch.setattr(sf.Config, "from_env", classmethod(lambda cls: cfg))
    written = []
    monkeypatch.setattr(sf.userconfig, "write_file_config", lambda updates: written.append(updates))
    monkeypatch.setattr(sf, "server_command", lambda: ["pf", "serve"])
    # bot? n | provider? y | provider="" (default claude-sdk) | desktop? n | cc? n
    sf.run_setup(input_fn=_fake_inputs(["n", "y", "", "n", "n"]))
    assert {"ask": {"provider": "claude-sdk"}} in written

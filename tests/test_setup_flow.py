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
    # register desktop? y | claude-code? y
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

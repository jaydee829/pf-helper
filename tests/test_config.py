import pf_helper.config as cfgmod
from pf_helper.config import Config


def test_aon_links_dir_under_data_dir(tmp_path):
    cfg = Config(data_dir=tmp_path)
    assert cfg.aon_links_dir == tmp_path / "aon_links"


def test_from_env_prefers_env(tmp_path, monkeypatch):
    monkeypatch.setenv("PF_HELPER_DATA_DIR", str(tmp_path / "envdata"))
    file_cfg = {"data_dir": str(tmp_path / "filedata")}
    monkeypatch.setattr(cfgmod.userconfig, "load_file_config", lambda: file_cfg)
    assert cfgmod.Config.from_env().data_dir == tmp_path / "envdata"


def test_from_env_uses_config_file_when_no_env(tmp_path, monkeypatch):
    monkeypatch.delenv("PF_HELPER_DATA_DIR", raising=False)
    file_cfg = {"data_dir": str(tmp_path / "filedata")}
    monkeypatch.setattr(cfgmod.userconfig, "load_file_config", lambda: file_cfg)
    assert cfgmod.Config.from_env().data_dir == tmp_path / "filedata"


def test_from_env_falls_back_to_default(monkeypatch):
    from pathlib import Path
    monkeypatch.delenv("PF_HELPER_DATA_DIR", raising=False)
    monkeypatch.setattr(cfgmod.userconfig, "load_file_config", dict)
    monkeypatch.setattr(cfgmod.userconfig, "data_dir_default", lambda: Path("/tmp/dd"))
    assert cfgmod.Config.from_env().data_dir == Path("/tmp/dd")

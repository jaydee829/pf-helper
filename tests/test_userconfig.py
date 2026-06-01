import pf_helper.userconfig as uc


def test_data_dir_default_prefers_source_checkout(tmp_path, monkeypatch):
    # a fake package dir whose parent HAS pyproject.toml -> repo/data
    pkg = tmp_path / "repo" / "pf_helper"
    pkg.mkdir(parents=True)
    (tmp_path / "repo" / "pyproject.toml").write_text("x")
    result = uc.data_dir_default(package_file=str(pkg / "userconfig.py"))
    assert result == tmp_path / "repo" / "data"


def test_data_dir_default_falls_back_to_platformdirs(tmp_path, monkeypatch):
    pkg = tmp_path / "site" / "pf_helper"
    pkg.mkdir(parents=True)  # no pyproject.toml at parent
    monkeypatch.setattr(uc.platformdirs, "user_data_dir", lambda app: str(tmp_path / "udd" / app))
    result = uc.data_dir_default(package_file=str(pkg / "userconfig.py"))
    assert result == tmp_path / "udd" / "pf-helper"


def test_config_path_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("PF_HELPER_CONFIG", str(tmp_path / "c.toml"))
    assert uc.config_path() == tmp_path / "c.toml"


def test_load_missing_returns_empty(tmp_path):
    assert uc.load_file_config(tmp_path / "nope.toml") == {}


def test_write_then_load_roundtrip_with_windows_path(tmp_path):
    p = tmp_path / "config.toml"
    uc.write_file_config(
        {"data_dir": r"C:\Users\x\data", "discord": {"token": "abc.def", "guild_id": 123}},
        path=p,
    )
    cfg = uc.load_file_config(p)
    assert cfg["data_dir"] == r"C:\Users\x\data"  # backslashes survive (literal string)
    assert cfg["discord"] == {"token": "abc.def", "guild_id": 123}


def test_write_merges_not_clobbers(tmp_path):
    p = tmp_path / "config.toml"
    uc.write_file_config({"discord": {"token": "t1"}}, path=p)
    uc.write_file_config({"discord": {"guild_id": 9}}, path=p)
    cfg = uc.load_file_config(p)
    assert cfg["discord"] == {"token": "t1", "guild_id": 9}

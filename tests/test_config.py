from pf_helper.config import Config


def test_aon_links_dir_under_data_dir(tmp_path):
    cfg = Config(data_dir=tmp_path)
    assert cfg.aon_links_dir == tmp_path / "aon_links"

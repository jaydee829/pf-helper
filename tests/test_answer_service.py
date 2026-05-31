from pf_helper.answer import Answer, AnswerConfig, AnswerError


def test_answer_defaults():
    a = Answer(text="hi")
    assert a.sources == []
    assert a.engine == ""


def test_answer_config_from_env(monkeypatch):
    monkeypatch.setenv("PF_HELPER_ASK_ENGINE", "B")
    monkeypatch.setenv("PF_HELPER_ASK_CACHE", "0")
    monkeypatch.setenv("PF_HELPER_ASK_CACHE_TTL_DAYS", "7")
    cfg = AnswerConfig.from_env()
    assert cfg.engine == "b"  # lower-cased
    assert cfg.cache_enabled is False
    assert cfg.cache_ttl_days == 7
    assert cfg.core.db_path.name == "pf2e.db"


def test_answer_error_reason():
    e = AnswerError("auth", "sign in")
    assert e.reason == "auth"

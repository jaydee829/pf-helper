import pytest

import pf_helper.bot.config as botcfg
from pf_helper.bot.config import BotConfig


def test_token_from_env_wins(monkeypatch):
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "envtok")
    monkeypatch.setattr(
        botcfg.userconfig, "load_file_config", lambda: {"discord": {"token": "filetok"}}
    )
    assert BotConfig.from_env().token == "envtok"


def test_token_from_config_file(monkeypatch):
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
    monkeypatch.setattr(
        botcfg.userconfig,
        "load_file_config",
        lambda: {"discord": {"token": "filetok", "guild_id": 7}},
    )
    cfg = BotConfig.from_env()
    assert cfg.token == "filetok" and cfg.guild_id == 7


def test_missing_token_raises(monkeypatch):
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
    monkeypatch.setattr(botcfg.userconfig, "load_file_config", dict)
    with pytest.raises(ValueError, match="DISCORD_BOT_TOKEN"):
        BotConfig.from_env()

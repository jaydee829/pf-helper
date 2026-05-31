"""discord.py client wiring /lookup, /search, /ask to the retriever and answerer."""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from pf_helper.answer import AnswerError, ask
from pf_helper.answer.config import AnswerConfig
from pf_helper.bot.config import BotConfig
from pf_helper.bot.embeds import answer_embed, lookup_embed, search_embeds, split_message
from pf_helper.retrieval.factory import build_retriever

_log = logging.getLogger(__name__)
_NO_INDEX = "Rules index not found — run `pf-helper-ingest` first."


def build_bot(bot_cfg: BotConfig, answer_cfg: AnswerConfig) -> commands.Bot:
    intents = discord.Intents.default()
    bot = commands.Bot(command_prefix="!", intents=intents)

    def retriever_or_none():
        if not answer_cfg.core.db_path.exists():
            return None
        return build_retriever(answer_cfg.core)

    @bot.event
    async def setup_hook():
        if bot_cfg.guild_id:
            guild = discord.Object(id=bot_cfg.guild_id)
            bot.tree.copy_global_to(guild=guild)
            await bot.tree.sync(guild=guild)
        else:
            await bot.tree.sync()

    @bot.tree.command(name="lookup", description="Look up a PF2e rules entry by exact name.")
    @app_commands.describe(name="Exact entry name", category="Optional category filter")
    async def lookup(interaction: discord.Interaction, name: str, category: str | None = None):
        r = retriever_or_none()
        if r is None:
            await interaction.response.send_message(_NO_INDEX, ephemeral=True)
            return
        detail = r.get(name, category=category or None)
        if detail is None:
            await interaction.response.send_message(
                f"No exact match for '{name}'. Try `/search`.", ephemeral=True
            )
            return
        await interaction.response.send_message(embed=lookup_embed(detail))

    @bot.tree.command(name="search", description="Search PF2e rules.")
    @app_commands.describe(query="Search text", category="Optional category filter")
    async def search(interaction: discord.Interaction, query: str, category: str | None = None):
        r = retriever_or_none()
        if r is None:
            await interaction.response.send_message(_NO_INDEX, ephemeral=True)
            return
        hits = r.search(query, category=category or None, limit=6)
        await interaction.response.send_message(embed=search_embeds(hits))

    @bot.tree.command(name="ask", description="Ask a PF2e rules question (uses Claude).")
    @app_commands.describe(question="Your rules question")
    async def ask_cmd(interaction: discord.Interaction, question: str):
        await interaction.response.defer(thinking=True)
        try:
            answer = await ask(question, answer_cfg)
        except AnswerError as e:
            await interaction.followup.send(str(e))
            return
        except Exception:  # noqa: BLE001 - never let one command crash the bot
            _log.exception("ask failed")
            await interaction.followup.send("Something went wrong answering that.")
            return
        chunks = split_message(answer.text)
        await interaction.followup.send(embed=answer_embed(answer))
        for extra in chunks[1:]:
            await interaction.followup.send(extra)

    return bot


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    bot_cfg = BotConfig.from_env()
    answer_cfg = AnswerConfig.from_env()
    bot = build_bot(bot_cfg, answer_cfg)
    bot.run(bot_cfg.token)


if __name__ == "__main__":
    main()

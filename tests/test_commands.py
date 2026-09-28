import time

import discord
import pytest
from discord import app_commands
from fakes import FakeInteraction

import commands as bot_commands
import db
import views
from embed_builder import build_embed


class _Bot:
    def __init__(self):
        self.tree = app_commands.CommandTree(discord.Client(intents=discord.Intents.none()))


@pytest.fixture
def cmds():
    bot = _Bot()
    bot_commands.setup(bot)
    return {c.name: c for c in bot.tree.get_commands()}


def _game(match_id, puuid, name, pompes, ended_at=None):
    db.record_game(match_id, "ARAM", ended_at or time.time(), [{
        "puuid": puuid, "name": name, "champion": "Jinx", "kills": 1, "deaths": 2, "assists": 3,
        "damage": 1000, "win": True, "pompes": pompes,
    }])


@pytest.fixture
def game():
    _game("EUW1_1", "pA", "A", 15)
    _game("EUW1_1", "pB", "B", 45)
    return build_embed([
        {"name": n, "champ": "Jinx", "kills": 1, "deaths": 2, "assists": 3, "damage": 1000,
         "win": True, "pompes": p, "icons": ""}
        for n, p in (("A", 15), ("B", 45))
    ], "EUW1_1")


def test_registered_commands_and_permissions(cmds):
    assert set(cmds) == {"session", "stats", "succes", "lier", "potes", "reset_session", "refresh_kda"}
    assert cmds["reset_session"].default_permissions.administrator
    assert cmds["refresh_kda"].default_permissions.administrator
    assert cmds["session"].default_permissions is None


async def test_session(cmds, game):
    db.mark_done("EUW1_1", "pB")
    i = FakeInteraction()
    await cmds["session"].callback(i)
    lines = i.reply[1].description.splitlines()
    assert lines[0].startswith("🥇 **B** — 45 pompes") and lines[0].endswith("✅ tout fait")
    assert lines[1].startswith("🥈 **A** — 15 pompes") and lines[1].endswith("✅ 0/15")


async def test_session_empty(cmds):
    i = FakeInteraction()
    await cmds["session"].callback(i)
    assert i.reply[0].startswith("Aucune partie")


async def test_reset_session_keeps_history(cmds, game):
    await cmds["reset_session"].callback(FakeInteraction())
    assert db.session_leaderboard() == []
    assert db.conn().execute("SELECT COUNT(*) FROM games").fetchone()[0] == 2


async def test_potes(cmds):
    db.record_team("EUW1_1", {"pB": "B"})
    db.record_team("EUW1_2", {"pB": "B"})
    i = FakeInteraction()
    await cmds["potes"].callback(i)
    assert "**B** — 2 partie(s) ensemble" in i.reply[1].description


async def test_refresh_kda(cmds):
    db.set_cached_kda("pB", 450, {"Kbar": 1, "Abar": 1, "Dbar": 1}, "B")
    i = FakeInteraction()
    await cmds["refresh_kda"].callback(i, "b")
    assert "supprimé" in i.reply[0] and db.get_cached_kda("pB", 450) is None
    i = FakeInteraction()
    await cmds["refresh_kda"].callback(i, "b")
    assert i.reply[2]                               # éphémère : plus rien à supprimer


async def test_lier_and_autocomplete(cmds, game):
    i = FakeInteraction(user_id=42)
    await cmds["lier"].callback(i, "inconnu")
    assert i.reply[2]
    await cmds["lier"].callback(FakeInteraction(user_id=42), "b")
    assert db.linked_player(42) == ("pB", "B")
    choices = await bot_commands.player_autocomplete(FakeInteraction(), "")
    assert {c.name for c in choices} == {"A", "B"}


async def test_stats(cmds, game):
    i = FakeInteraction(user_id=7)
    await cmds["stats"].callback(i, None)
    assert i.reply[2]                               # ni joueur ni /lier

    i = FakeInteraction(user_id=7)
    await cmds["stats"].callback(i, "a")
    embed = i.reply[1]
    assert embed.title == "📈 Stats de A"
    assert [f.value for f in embed.fields if "Faites" in f.name] == ["0/15"]

    db.link_discord(7, "pB", "B")
    i = FakeInteraction(user_id=7)
    await cmds["stats"].callback(i, None)
    assert i.reply[1].title == "📈 Stats de B"


async def test_done_button(game):
    button = views.DoneButton("EUW1_1")
    assert button.item.custom_id == "pompes:done:EUW1_1"

    i = FakeInteraction(user_id=42, embed=game)
    await button.callback(i)
    assert i.reply[2] and "/lier" in i.reply[0]      # pas encore lié

    db.link_discord(42, "pB", "B")
    i = FakeInteraction(user_id=42, embed=game)
    await button.callback(i)
    assert i.response.edited.fields[2].value.splitlines() == ["**15**", "**45** ✅"]
    assert "45 pompes validées" in i.followup.messages[0]

    i = FakeInteraction(user_id=42, embed=game)
    await button.callback(i)
    assert i.reply[0].startswith("Déjà")

    i = FakeInteraction(user_id=42, embed=game)
    await views.DoneButton("EUW1_2").callback(i)
    assert "ne fait pas partie" in i.reply[0]


def test_button_template_matches_custom_id():
    assert views.DoneButton.__discord_ui_compiled_template__.fullmatch("pompes:done:EUW1_7913452976")

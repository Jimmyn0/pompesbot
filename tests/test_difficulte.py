import time
from types import SimpleNamespace

import discord
import pytest
from discord import app_commands
from fakes import FakeInteraction

import commands as bot_commands
import config
import db
from pushups import calculate_pushups, get_player_category

AVG = {"Kbar": 10, "Abar": 20, "Dbar": 10}


@pytest.fixture
def cmds():
    bot = SimpleNamespace(tree=app_commands.CommandTree(discord.Client(intents=discord.Intents.none())))
    bot_commands.setup(bot)
    return {c.name: c for c in bot.tree.get_commands()}


@pytest.fixture
def players():
    """A (ELT dans players.json) et B (sans niveau) ont chacun joué une partie."""
    for puuid, name in (("pA", "A"), ("pB", "B")):
        db.record_game(f"EUW1_{name}", "ARAM", time.time(), [{
            "puuid": puuid, "name": name, "champion": "Jinx", "kills": 1, "deaths": 1, "assists": 1,
            "damage": 1, "win": True, "pompes": 10}])


def _admin(interaction):
    interaction.user.guild_permissions = SimpleNamespace(administrator=True)
    return interaction


def test_level_names_and_order():
    # players.json de test : STD (base 15) et ELT (base 30), triés du plus facile au plus dur.
    assert config.LEVELS == ["STD", "ELT"]
    assert [config.level_label(c) for c in config.LEVELS] == ["Échauffement", "Bodybuilder"]
    assert config.level_label("CNF") == "Athlète"


def test_players_json_level_is_kept_after_rename():
    assert get_player_category("A", "pA")[0] == "ELT"          # repris de players.json…
    assert db.get_level("pA") == "ELT"                          # …et enregistré pour ce compte
    assert get_player_category("A-renommé", "pA")[0] == "ELT"   # survit au changement de pseudo


def test_chosen_level_drives_the_formula():
    db.set_level("pA", "STD", "A")                               # A choisit Échauffement
    total, category, b = calculate_pushups(10, 10, 20, "A", AVG, win=True, puuid="pA")
    assert (total, category, b["level"]) == (15, "STD", "Échauffement")


async def test_show_and_change_own_level(cmds, players):
    i = FakeInteraction(user_id=42)
    await cmds["difficulte"].callback(i, None, None)
    assert i.reply[2] and "/lier" in i.reply[0]                 # pas encore lié

    await cmds["lier"].callback(FakeInteraction(user_id=42), "b", "ELT")
    assert db.get_level("pB") == "ELT"

    i = FakeInteraction(user_id=42)
    await cmds["difficulte"].callback(i, None, None)
    content, embed, ephemeral = i.reply
    assert ephemeral and embed.title == "🏋️ Niveau de B : Bodybuilder"
    assert embed.description.splitlines()[0].startswith("**Échauffement** — base 15")

    i = FakeInteraction(user_id=42)
    await cmds["difficulte"].callback(i, "STD", None)
    assert "passe au niveau **Échauffement**" in i.reply[0] and db.get_level("pB") == "STD"

    i = FakeInteraction(user_id=42)
    await cmds["difficulte"].callback(i, "INCONNU", None)
    assert i.reply[2] and db.get_level("pB") == "STD"


async def test_only_admins_change_others(cmds, players):
    db.link_discord(42, "pB", "B")
    i = FakeInteraction(user_id=42)
    await cmds["difficulte"].callback(i, "STD", "A")
    assert i.reply[2] and "admin" in i.reply[0] and db.get_level("pA") != "STD"

    i = FakeInteraction(user_id=42)
    await cmds["difficulte"].callback(i, None, "a")              # consulter : autorisé
    assert "Niveau de A" in i.reply[1].title

    await cmds["difficulte"].callback(_admin(FakeInteraction(user_id=1)), "STD", "a")
    assert db.get_level("pA") == "STD"

    i = FakeInteraction(user_id=42)
    await cmds["difficulte"].callback(i, "ELT", "b")             # soi-même via le pseudo : autorisé
    assert db.get_level("pB") == "ELT"


async def test_stats_shows_level(cmds, players):
    i = FakeInteraction(user_id=7)
    await cmds["stats"].callback(i, "a")
    assert i.reply[1].description == "Niveau **Bodybuilder**"

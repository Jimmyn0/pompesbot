"""Boutons de détail, séries, succès et records, de bout en bout via la boucle."""

import discord
import pytest
from discord import app_commands
from fakes import FakeBot, FakeChannel, FakeInteraction, match, participant

import commands as bot_commands
import db
import loop
import views

P = participant


@pytest.fixture
async def ready(riot):
    """Propriétaire A et pote B déjà connus, premier scan fait."""
    riot.add("EUW1_10", match(400, [P(1, "pA", 100), P(2, "pB", 100)]))
    riot.add("EUW1_11", match(450, [P(1, "pA", 100), P(2, "pB", 100)]))
    riot.first_blood = (None, None)
    channel = FakeChannel()
    await loop.scan(FakeBot(channel), 1)
    return riot, channel


def _aram(riot, match_id, now, win=True, a_deaths=5, **kwargs):
    riot.add(match_id, match(450, [
        P(1, "pA", 100, 5, a_deaths, 10, 20000, win=win, champion="Karma"),
        P(2, "pB", 100, 5, 5, 10, 10000, win=win, champion="Kayle"),
    ], ended_ms=int(now * 1000), **kwargs))


async def test_loss_streak_multiplies_and_unlocks_once(ready, now):
    riot, channel = ready
    for i in range(4):
        _aram(riot, f"EUW1_{20 + i}", now - (4 - i) * 600, win=False)
        await loop.scan(FakeBot(channel), 1)

    embeds = channel.embeds
    assert len(embeds) == 4
    assert "🌧️" not in embeds[1].fields[2].value                  # 2e défaite
    assert "🌧️" in embeds[2].fields[2].value                      # 3e défaite : ×1,2
    assert "Série noire ×1,2" in embeds[2].fields[-1].value       # légende
    succes = [f for f in embeds[2].fields if f.name == "🏅 Succès débloqués"]
    assert succes and "Série noire" in succes[0].value
    assert not [f for f in embeds[3].fields if f.name == "🏅 Succès débloqués"]   # pas deux fois
    assert db.get_breakdown("EUW1_22", 1)["breakdown"]["loss_streak"] == 3


async def test_achievements_not_saved_when_discord_fails(ready, now):
    riot, channel = ready
    _aram(riot, "EUW1_30", now, a_deaths=0)
    channel.fail_times = 1
    await loop.scan(FakeBot(channel), 1)
    assert not db.has_achievement("pA", "intouchable")

    await loop.scan(FakeBot(channel), 1)
    succes = [f for f in channel.embeds[0].fields if f.name == "🏅 Succès débloqués"]
    assert "**A** — 🛡️ Intouchable" in succes[0].value
    assert db.has_achievement("pA", "intouchable")


async def test_detail_buttons(ready, now, monkeypatch):
    riot, channel = ready

    async def icon(champion_id, champion_name):
        return "<:Karma:123>" if champion_name == "Karma" else champion_name

    monkeypatch.setattr(loop, "champion_icon", icon)
    _aram(riot, "EUW1_40", now)
    await loop.scan(FakeBot(channel), 1)

    _, view = channel.sent[0]
    detail = [c for c in view.children if c.custom_id.startswith("pompes:detail:")]
    faces = {(b.item.label, str(b.item.emoji) if b.item.emoji else None) for b in detail}
    assert faces == {("A", "<:Karma:123>"), ("Kayle · B", None)}     # icône si disponible, sinon nom du champion
    assert all(b.item.row < 4 for b in detail) and view.children[-1].item.row == 4

    i = FakeInteraction()
    await views.DetailButton("EUW1_40", 1).callback(i)
    content, embed, ephemeral = i.reply
    assert ephemeral and embed.title.startswith("💪 A — ")
    assert "Catégorie ELT" in embed.description and "`5/5/10`" in embed.description
    assert "Base" in embed.description and "Kills et assists" in embed.description

    i = FakeInteraction()
    await views.DetailButton("EUW1_40", 9).callback(i)
    assert i.reply[2] and "indisponible" in i.reply[0]


async def test_done_button_unlocks_centurion(ready, now):
    riot, channel = ready
    db.record_game("EUW1_50", "ARAM", now, [{
        "puuid": "pB", "name": "B", "champion": "Kayle", "kills": 0, "deaths": 9, "assists": 0,
        "damage": 0, "win": False, "pompes": 100, "pid": 2}])
    db.link_discord(42, "pB", "B")
    embed = discord.Embed(title="t")
    embed.add_field(name="Joueur", value="**B**").add_field(name="x", value="x").add_field(name="p", value="**100**")
    i = FakeInteraction(user_id=42, embed=embed)
    await views.DoneButton("EUW1_50").callback(i)
    assert "Centurion" in i.followup.messages[-1]


async def test_succes_command(ready):
    db.link_discord(42, "pA", "A")
    db.unlock("pA", "pentakill")
    bot = type("B", (), {})()
    bot.tree = app_commands.CommandTree(discord.Client(intents=discord.Intents.none()))
    bot_commands.setup(bot)
    cmd = {c.name: c for c in bot.tree.get_commands()}["succes"]

    i = FakeInteraction(user_id=42)
    await cmd.callback(i, None)
    embed = i.reply[1]
    assert embed.title == "🏅 Succès de A (1/9)"
    assert "🖐️ **Pentakill**" in embed.description and "🔒 ~~Intouchable~~" in embed.description

    i = FakeInteraction(user_id=7)
    await cmd.callback(i, None)
    assert i.reply[2]

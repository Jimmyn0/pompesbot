from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fakes import FakeBot, FakeChannel

import db
import loop

TZ = ZoneInfo("Europe/Paris")
MONDAY = datetime(2026, 9, 28, 10, 30, tzinfo=TZ)     # semaine 2026-W40


def _game(match_id, puuid, name, pompes, ended_at):
    db.record_game(match_id, "ARAM", ended_at.timestamp(), [{
        "puuid": puuid, "name": name, "champion": "Jinx", "kills": 1, "deaths": 2, "assists": 3,
        "damage": 1000, "win": True, "pompes": pompes,
    }])


@pytest.fixture
def channel():
    return FakeChannel()


async def _recap(channel, when):
    await loop.post_weekly_recap(FakeBot(channel), 1, when)


def test_recap_moment():
    assert loop.recap_moment(datetime(2026, 10, 1, 18, 0, tzinfo=TZ)) == datetime(2026, 9, 28, 10, 0, tzinfo=TZ)


async def test_first_launch_posts_nothing(channel):
    _game("EUW1_1", "pA", "A", 20, MONDAY - timedelta(days=1))
    await _recap(channel, MONDAY)
    assert channel.sent == [] and db.get_meta("last_recap_week") == "2026-W40"


async def test_weekly_recap(channel):
    db.set_meta("last_recap_week", "2026-W39")
    _game("EUW1_1", "pA", "A", 20, MONDAY - timedelta(days=1))
    _game("EUW1_2", "pB", "B", 50, MONDAY - timedelta(days=2))
    _game("EUW1_0", "pB", "B", 99, MONDAY - timedelta(days=9))      # hors semaine
    db.mark_done("EUW1_1", "pA")

    await _recap(channel, MONDAY.replace(hour=9))
    assert channel.sent == []                                          # trop tôt

    await _recap(channel, MONDAY)
    embed = channel.embeds[0]
    fields = {f.name: f.value for f in embed.fields}
    assert embed.title == "📅 Récap de la semaine"
    assert fields["Classement"].splitlines()[0].startswith("🥇 **B** — 50 pompes")
    assert fields["😇 Le plus sage"].startswith("**A**")
    assert fields["💀 Pire partie"].startswith("**B** — 50 pompes")
    assert fields["🧾 Pompes pas encore faites"] == "**B** — 50"

    await _recap(channel, MONDAY + timedelta(hours=3))
    assert len(channel.sent) == 1                                      # pas deux fois


async def test_recap_caught_up_later_in_week(channel):
    db.set_meta("last_recap_week", "2026-W39")
    _game("EUW1_1", "pA", "A", 20, MONDAY - timedelta(days=1))
    await _recap(channel, datetime(2026, 9, 30, 18, 0, tzinfo=TZ))     # bot éteint lundi, relancé mercredi
    assert len(channel.sent) == 1 and db.get_meta("last_recap_week") == "2026-W40"


async def test_empty_week_posts_nothing_but_is_marked(channel):
    db.set_meta("last_recap_week", "2026-W39")
    await _recap(channel, MONDAY)
    assert channel.sent == [] and db.get_meta("last_recap_week") == "2026-W40"

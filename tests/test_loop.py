import asyncio

import pytest
from fakes import FakeBot, FakeChannel, match, participant

import db
import loop

P = participant


def _ms(ts):
    return int(ts * 1000)


@pytest.fixture
def seeded(riot, now):
    """Historique de départ : B joue deux fois avec A (pote), R1 une seule fois."""
    riot.add("EUW1_10", match(400, [P(1, "pA", 100), P(2, "pB", 100)]))
    riot.add("EUW1_11", match(450, [P(1, "pA", 100), P(2, "pB", 100), P(3, "pR1", 100)]))
    return riot


async def _scan(channel):
    await loop.scan(FakeBot(channel), 1)
    await asyncio.sleep(0)          # laisse tourner le préchauffage KDA


async def test_first_scan_learns_friends_without_posting(seeded):
    channel = FakeChannel()
    await _scan(channel)
    assert channel.sent == []
    assert db.is_processed("EUW1_11")
    assert {n for n, _ in db.known_friends().values()} == {"B"}
    await asyncio.sleep(0.01)
    assert set(seeded.kda_calls) == {"A", "B"}


async def test_only_owner_and_friends_get_pushups(seeded, now):
    channel = FakeChannel()
    await _scan(channel)
    seeded.add("EUW1_12", match(450, [
        P(1, "pA", 100, 10, 5, 20, 40000), P(2, "pB", 100, 2, 15, 5, 10000),
        P(3, "pR2", 100, 9, 1, 9, 60000), P(6, "pO", 200, 5, 5, 5, 50000, win=False),
    ], ended_ms=_ms(now)))
    await _scan(channel)

    assert len(channel.sent) == 1
    embed, view = channel.sent[0]
    assert "ARAM" in embed.title
    ids = [c.custom_id for c in view.children]
    assert ids == ["pompes:detail:EUW1_12:1", "pompes:detail:EUW1_12:2", "pompes:done:EUW1_12"]   # ordre de l'embed
    assert {r["name"]: r["total"] for r in db.session_leaderboard()} == {"A": 15, "B": 45}

    await _scan(channel)
    assert len(channel.sent) == 1          # pas de re-post


async def test_discord_failure_is_retried_without_double_count(seeded, now):
    channel = FakeChannel()
    await _scan(channel)
    seeded.add("EUW1_12", match(450, [P(1, "pA", 100, 1, 1, 1)], ended_ms=_ms(now)))

    channel.fail_times = 1
    await _scan(channel)
    assert channel.sent == [] and db.session_leaderboard() == [] and not db.is_processed("EUW1_12")

    await _scan(channel)
    assert len(channel.sent) == 1
    assert db.session_leaderboard()[0]["n"] == 1


async def test_match_abandoned_after_max_attempts(seeded):
    channel = FakeChannel()
    await _scan(channel)
    seeded.history.append("EUW1_99")      # détail introuvable
    for _ in range(loop.MAX_ATTEMPTS - 1):
        await _scan(channel)
        assert not db.is_processed("EUW1_99")
    await _scan(channel)
    assert db.is_processed("EUW1_99")


async def test_out_of_scope_and_too_old_matches_are_skipped(seeded, now):
    channel = FakeChannel()
    await _scan(channel)
    seeded.add("EUW1_20", match(420, [P(1, "pA", 100)], ended_ms=_ms(now)))
    seeded.add("EUW1_21", match(450, [P(1, "pA", 100)], ended_ms=_ms(now - 13 * 3600)))
    await _scan(channel)
    assert channel.sent == []
    assert db.is_processed("EUW1_20") and db.is_processed("EUW1_21")


async def test_arena(seeded, now):
    channel = FakeChannel()
    seeded.add("EUW1_12", match(450, [P(1, "pA", 100), P(3, "pR1", 100)]))   # R1 : 2e partie avec A -> pote
    await _scan(channel)
    seeded.add("EUW1_30", match(1750, [
        P(1, "pA", 0, 3, 2, 1, 30000, sub=1), P(2, "pB", 0, 3, 2, 1, 5000, sub=1),
        P(3, "pR1", 0, 1, 2, 1, 20000, win=False, sub=2), P(4, "pO", 0, 1, 2, 1, 9000, win=False, sub=2),
        P(5, "pR3", 0, 1, 2, 1, 1000, win=False, sub=3),
    ], ended_ms=_ms(now), game_mode="CHERRY"))
    await _scan(channel)

    embed = channel.embeds[0]
    assert "Arena" in embed.title
    names = [line.split("**")[1] for line in embed.fields[0].value.splitlines()]
    pompes = dict(zip(names, embed.fields[2].value.splitlines(), strict=True))
    assert set(names) == {"A", "B", "R1"}             # R1 est un pote même dans un autre duo
    assert "💥" in pompes["A"] and "💥" in pompes["R1"] and "💥" not in pompes["B"]   # top dégâts par duo
    assert "🗡️" in pompes["A"] and "💀" in pompes["B"]

    # Un inconnu recroisé dans le lobby (autre duo) ne devient pas un pote.
    seeded.add("EUW1_31", match(1750, [P(1, "pA", 0, sub=1), P(5, "pR3", 0, sub=3)],
                                ended_ms=_ms(now), game_mode="CHERRY"))
    await _scan(channel)
    assert not db.is_friend("pR3")


async def test_new_modes(seeded, now):
    channel = FakeChannel()
    await _scan(channel)
    seeded.add("EUW1_40", match(2400, [P(1, "pA", 100)], ended_ms=_ms(now), game_mode="KIWI"))
    seeded.add("EUW1_41", match(1900, [P(1, "pA", 100)], ended_ms=_ms(now)))
    await _scan(channel)
    assert [e.title.split(" — ")[0] for e in channel.embeds] == ["Fin de partie ARAM Mayhem", "Fin de partie URF"]


async def test_idle_session_is_closed_with_summary(now):
    db.record_game("EUW1_1", "ARAM", now - 7 * 3600, [{
        "puuid": "pA", "name": "A", "champion": "Jinx", "kills": 1, "deaths": 1, "assists": 1,
        "damage": 1, "win": True, "pompes": 20}])
    channel = FakeChannel()
    await loop._close_idle_session(channel, now)
    assert len(channel.sent) == 1 and "Fin de session" in channel.embeds[0].title
    await loop._close_idle_session(channel, now)
    assert len(channel.sent) == 1


async def test_scan_exceptions_do_not_stop_the_loop(seeded, monkeypatch):
    async def boom(*args, **kwargs):
        raise ValueError("boom")

    monkeypatch.setattr(loop, "get_puuid", boom)
    league_loop = loop.make_league_loop(FakeBot(FakeChannel()), 1)
    await league_loop.coro()          # ne lève pas


def test_match_order():
    assert loop._match_order("EUW1_7913452976") == 7913452976
    assert sorted(["EUW1_10", "EUW1_9"], key=loop._match_order) == ["EUW1_9", "EUW1_10"]

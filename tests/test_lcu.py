"""Parties lues depuis le client League (ARAM Mayhem, invisible dans l'API Riot)."""

import pytest
from fakes import FakeBot, FakeChannel, lcu_game

import db
import lcu
import loop


def _team(win_100=True, a_deaths=11):
    """A, B, C (potes potentiels) dans l'équipe 200 avec deux inconnus ; 5 adversaires en 100."""
    return [
        ("pO1", "Adv1", 100, 13, 8, 32, 39544, win_100), ("pO2", "Adv2", 100, 15, 5, 28, 47798, win_100),
        ("pO3", "Adv3", 100, 4, 7, 32, 27718, win_100), ("pO4", "Adv4", 100, 10, 3, 34, 43108, win_100),
        ("pO5", "Adv5", 100, 17, 3, 31, 47322, win_100),
        ("pR", "Random", 200, 7, 14, 10, 16330, not win_100), ("pB", "B", 200, 5, 14, 9, 21987, not win_100),
        ("pC", "C", 200, 2, 12, 8, 10665, not win_100), ("pD", "D", 200, 6, 8, 8, 12373, not win_100),
        ("pA", "A", 200, 6, a_deaths, 8, 16943, not win_100),
    ]


# --- module lcu --------------------------------------------------------------------------

async def test_to_match_info(client_lol):
    info = await lcu.to_match_info(lcu_game(7995738556, _team(), created_ms=1_000_000))
    assert info["queueId"] == 2400 and info["gameMode"] == "KIWI"
    assert info["gameEndTimestamp"] == 1_000_000 + 1200 * 1000
    a = next(p for p in info["participants"] if p["riotIdGameName"] == "A")
    assert a["puuid"] == a["lcuPuuid"] == "brut-A" and a["riotIdTagline"] == "EUW"
    assert (a["riotIdGameName"], a["teamId"], a["kills"], a["deaths"], a["assists"]) == ("A", 200, 6, 11, 8)
    assert a["totalDamageDealtToChampions"] == 16943 and a["win"] is False
    assert a["championName"] == "Champ110"
    assert lcu.match_id(lcu_game(7995738556, _team(), 0)) == "EUW1_7995738556"


async def test_kda_baseline_from_shared_games(client_lol):
    for i in range(3):
        client_lol.add(lcu_game(100 + i, _team(a_deaths=10 + i), created_ms=i))
    client_lol.add(lcu_game(200, _team(), created_ms=9, queue=450, game_mode="ARAM"))   # autre mode : ignoré
    assert await lcu.kda_baseline("brut-A", 2400) == {"Kbar": 6.0, "Abar": 8.0, "Dbar": 11.0}
    assert await lcu.kda_baseline("brut-A", 2400, min_games=4) is None
    assert await lcu.kda_baseline("pZ", 2400) is None


async def test_client_closed_returns_none(tmp_path):
    client = lcu.LcuClient([str(tmp_path / "absent")])
    assert await client.get("/lol-summoner/v1/current-summoner") is None


def test_lockfile_parsing(tmp_path):
    path = tmp_path / "lockfile"
    path.write_text("LeagueClient:1234:51889:secret:https")
    assert lcu.LcuClient([str(tmp_path / "absent"), str(path)])._read_lockfile() == ("51889", "secret")
    path.write_text("corrompu")
    assert lcu.LcuClient([str(path)])._read_lockfile() is None


# --- intégration dans la boucle ---------------------------------------------------------

@pytest.fixture
async def seeded(riot, client_lol, now):
    """Riot : historique vide (aucune partie Mayhem). Client : 2 parties passées avec B et C."""
    client_lol.add(lcu_game(1, _team(), created_ms=int((now - 3 * 86400) * 1000)))
    client_lol.add(lcu_game(2, _team(), created_ms=int((now - 2 * 86400) * 1000)))
    channel = FakeChannel()
    await loop.scan(FakeBot(channel), 1)
    return client_lol, channel


async def test_first_read_learns_friends_without_posting(seeded):
    client_lol, channel = seeded
    assert channel.sent == []
    assert db.is_processed("EUW1_1") and db.is_processed("EUW1_2")
    assert {n for n, _ in db.known_friends().values()} == {"B", "C", "D", "Random"}   # vus 2 fois


async def test_new_mayhem_game_is_posted_once(seeded, now):
    client_lol, channel = seeded
    client_lol.add(lcu_game(3, _team(), created_ms=int((now - 1500) * 1000)))
    await loop.scan(FakeBot(channel), 1)

    assert len(channel.sent) == 1
    embed, view = channel.sent[0]
    assert embed.title.startswith("Fin de partie ARAM Mayhem — 💀 DÉFAITE")
    names = {line.split("**")[1] for line in embed.fields[0].value.splitlines()}
    assert "A" in names and not names & {"Adv1", "Adv2"}                     # pas les adversaires
    assert view.children[-1].custom_id == "pompes:done:EUW1_3"
    assert db.get_breakdown("EUW1_3", 10)["breakdown"]["category"] == "ELT"

    await loop.scan(FakeBot(channel), 1)
    assert len(channel.sent) == 1                                              # pas de re-post


async def test_kda_baseline_comes_from_client(seeded, now, riot):
    client_lol, channel = seeded
    client_lol.add(lcu_game(3, _team(), created_ms=int((now - 1500) * 1000)))
    await loop.scan(FakeBot(channel), 1)
    assert db.get_cached_kda("pA", 2400) == {"Kbar": 6.0, "Abar": 8.0, "Dbar": 11.0}
    assert ("A", 2400) not in riot.kda_queries                                # jamais demandé à Riot


async def test_other_account_or_closed_client(seeded, now):
    client_lol, channel = seeded
    client_lol.add(lcu_game(3, _team(), created_ms=int((now - 1500) * 1000)))
    client_lol.riot_id = ("Autre", "EUW")                                    # quelqu'un d'autre est connecté
    await loop.scan(FakeBot(channel), 1)
    client_lol.riot_id = None                                                # client fermé
    await loop.scan(FakeBot(channel), 1)
    assert channel.sent == [] and not db.is_processed("EUW1_3")

    client_lol.riot_id = ("a", "euw")                                        # réouverture (casse ignorée)
    await loop.scan(FakeBot(channel), 1)
    assert len(channel.sent) == 1


async def test_old_games_are_not_caught_up(seeded, now):
    client_lol, channel = seeded
    client_lol.add(lcu_game(3, _team(), created_ms=int((now - 13 * 3600) * 1000)))
    await loop.scan(FakeBot(channel), 1)
    assert channel.sent == [] and db.is_processed("EUW1_3")


async def test_other_queues_left_to_riot(seeded, now):
    client_lol, channel = seeded
    client_lol.add(lcu_game(3, _team(), created_ms=int((now - 1500) * 1000), queue=450, game_mode="ARAM"))
    await loop.scan(FakeBot(channel), 1)
    assert channel.sent == [] and not db.is_processed("EUW1_3")              # l'API Riot s'en charge


def _with_newcomer(name):
    """Même partie, mais « Random » est remplacé par un inconnu vu pour la première fois."""
    return [(f"p{name}", name, *row[2:]) if row[1] == "Random" else row for row in _team()]


async def test_only_owner_and_friends_are_asked_to_riot(riot, client_lol, now):
    client_lol.add(lcu_game(1, _team(), created_ms=int((now - 3 * 86400) * 1000)))
    client_lol.add(lcu_game(2, _team(), created_ms=int((now - 2 * 86400) * 1000)))
    client_lol.add(lcu_game(3, _with_newcomer("Once"), created_ms=int((now - 86400) * 1000)))
    channel = FakeChannel()
    await loop.scan(FakeBot(channel), 1)                      # 1re lecture : historique
    asked = set(riot.puuid_calls)
    assert {"A", "B", "C", "D", "Random"} <= asked               # toi + joueurs vus 2 fois
    assert "Once" not in asked                                   # vu une seule fois : aucun appel
    assert not asked & {"Adv1", "Adv2", "Adv3", "Adv4", "Adv5"}  # jamais les adversaires

    # Nouvelle partie : « Once » revient (2e fois) -> converti et reconnu comme pote.
    client_lol.add(lcu_game(4, _with_newcomer("Once"), created_ms=int((now - 1500) * 1000)))
    riot.puuid_calls.clear()
    await loop.scan(FakeBot(channel), 1)
    assert "Once" in riot.puuid_calls and db.is_friend("pOnce")
    assert "Adv1" not in riot.puuid_calls


async def test_puuid_is_asked_to_riot_once(monkeypatch):
    import riot_api

    calls = []

    async def fake_get(path, params=None):
        calls.append(path)
        return {"puuid": "P-" + path.rsplit("/", 2)[-2]}

    monkeypatch.setattr(riot_api.client, "get", fake_get)
    riot_api.puuid_cache.clear()
    assert await riot_api.get_puuid("Bard est là", "EUW") == "P-Bard%20est%20l%C3%A0"
    riot_api.puuid_cache.clear()                                 # redémarrage : mémoire vide…
    assert await riot_api.get_puuid("BARD EST LÀ", "euw") == "P-Bard%20est%20l%C3%A0"   # …mais la base s'en souvient
    assert len(calls) == 1

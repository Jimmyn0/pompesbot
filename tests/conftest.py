"""
Configuration commune des tests.

Les modules du bot lisent leur configuration à l'import (players.json, .env) : on prépare donc
un dossier de données temporaire AVANT d'importer quoi que ce soit du bot.
"""

import json
import os
import sys
import tempfile
import time

import pytest

_DATA_DIR = tempfile.mkdtemp(prefix="pompesbot-tests-")
with open(os.path.join(_DATA_DIR, "players.json"), "w", encoding="utf-8") as f:
    json.dump({
        "OWNER": {"name": "A", "tag": "EUW"},
        "PLAYER_CATEGORIES": {
            # STD en premier : vérifie que l'ordre des clés n'a pas d'importance.
            "STD": {"players": [],    "base": 15, "min_pompes": 5,  "mult_mort": 12, "mult_kill": 10},
            "ELT": {"players": ["A"], "base": 30, "min_pompes": 15, "mult_mort": 18, "mult_kill": 18},
        },
    }, f)
os.environ["POMPESBOT_DATA_DIR"] = _DATA_DIR
os.environ.setdefault("RIOT_API_KEY", "test")
# Jamais le vrai client League du PC pendant les tests (cf. fixture client_lol).
os.environ["LCU_LOCKFILE"] = os.path.join(_DATA_DIR, "pas-de-lockfile")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fakes import FakeClientLoL, FakeRiot  # noqa: E402

import db  # noqa: E402
import lcu  # noqa: E402
import loop  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db(tmp_path):
    """Base SQLite neuve pour chaque test."""
    db.init(str(tmp_path / "test.db"))
    loop._failures.clear()
    loop._warmup_task = None
    yield
    db.conn().close()


@pytest.fixture
def riot(monkeypatch):
    """Fausse API Riot branchée sur la boucle (aucun appel réseau)."""
    fake = FakeRiot()
    for name in ("get_puuid", "get_recent_match_ids", "get_match_detail", "get_first_blood", "get_player_kda_stats"):
        monkeypatch.setattr(loop, name, getattr(fake, name))
    return fake


@pytest.fixture
def client_lol(monkeypatch):
    """Faux client League (historique local) branché sur lcu."""
    fake = FakeClientLoL()
    for name in ("current_riot_id", "recent_games", "game_detail", "first_blood", "champion_name"):
        monkeypatch.setattr(lcu, name, getattr(fake, name))
    return fake


@pytest.fixture
def now():
    return time.time()

import json
import sqlite3
import time

import db


def _game(match_id, puuid="pA", name="A", pompes=20, ended_at=None, mode="ARAM"):
    db.record_game(match_id, mode, ended_at or time.time(), [{
        "puuid": puuid, "name": name, "champion": "Jinx", "kills": 1, "deaths": 2, "assists": 3,
        "damage": 1000, "win": True, "pompes": pompes,
    }])


def test_kda_cache_roundtrip_and_invalidate():
    db.set_cached_kda("pA", 450, {"Kbar": 1, "Abar": 2, "Dbar": 3}, "Alpha")
    assert db.get_cached_kda("pA", 450) == {"Kbar": 1, "Abar": 2, "Dbar": 3}
    assert db.get_cached_kda("pA", 900) is None
    assert db.invalidate_kda("alpha")                 # insensible à la casse
    assert db.get_cached_kda("pA", 450) is None
    assert not db.invalidate_kda("alpha")


def test_session_leaderboard_and_reset_keeps_history():
    _game("EUW1_1", pompes=10)
    _game("EUW1_2", pompes=15)
    _game("EUW1_2", puuid="pB", name="B", pompes=40)
    board = db.session_leaderboard()
    assert [(r["name"], r["total"], r["n"]) for r in board] == [("B", 40, 1), ("A", 25, 2)]

    db.reset_session()
    assert db.session_leaderboard() == []
    assert db.conn().execute("SELECT COUNT(*) FROM games").fetchone()[0] == 3


def test_latest_name_is_used_after_rename():
    _game("EUW1_1", name="OldName", ended_at=1000)
    _game("EUW1_2", name="NewName", ended_at=2000)
    assert db.session_leaderboard()[0]["name"] == "NewName"


def test_mark_done_statuses():
    _game("EUW1_1", pompes=12)
    assert db.mark_done("EUW1_1", "pA") == ("ok", 12, "A")
    assert db.mark_done("EUW1_1", "pA") == ("deja", 12, "A")
    assert db.mark_done("EUW1_1", "pZ") == ("absent", 0, "")
    assert db.session_leaderboard()[0]["done"] == 12


def test_rollover_if_idle():
    now = time.time()
    _game("EUW1_1", ended_at=now - 7 * 3600)
    sid = db.current_session_id()
    assert db.rollover_if_idle(now - 3 * 3600, 6 * 3600) is None     # 4 h d'écart : on garde
    assert db.rollover_if_idle(now, 6 * 3600) == sid                  # 7 h : on clôt
    assert db.current_session_id() != sid
    assert db.rollover_if_idle(now, 6 * 3600) is None                 # session vide : rien à clore


def test_friend_window_keeps_last_40_matches():
    for k in range(45):
        db.record_team(f"EUW1_{100 + k}", {"pX": "X"} if k < 2 else {})
    assert db.conn().execute("SELECT COUNT(DISTINCT match_id) FROM owner_teams").fetchone()[0] == 40
    assert not db.is_friend("pX")          # ses 2 parties sont sorties de la fenêtre


def test_friend_needs_two_games():
    db.record_team("EUW1_1", {"pB": "B", "pR": "R"})
    assert not db.is_friend("pB")
    db.record_team("EUW1_2", {"pB": "B2"})
    assert db.is_friend("pB") and not db.is_friend("pR")
    assert db.known_friends() == {"pB": ("B2", 2)}


def test_links_and_player_lookup():
    _game("EUW1_1", puuid="pB", name="Bard est là")
    assert db.find_player("BARD EST LÀ") == ("pB", "Bard est là")
    assert db.find_player("inconnu") is None
    db.link_discord(42, "pB", "Bard est là")
    assert db.linked_player(42) == ("pB", "Bard est là")


def test_player_stats():
    _game("EUW1_1", pompes=10)
    _game("EUW1_2", pompes=30)
    db.mark_done("EUW1_1", "pA")
    stats = db.player_stats("pA")
    assert (stats["n"], stats["total"], stats["avg"], stats["done"]) == (2, 40, 20.0, 10)
    assert stats["worst"]["pompes"] == 30 and stats["best"]["pompes"] == 10
    assert stats["favorite"] == ("Jinx", 2) and stats["cursed"] == ("Jinx", 20.0, 2)
    assert db.player_stats("pZ") is None


def test_adds_done_at_to_existing_database(tmp_path):
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.execute("CREATE TABLE games (match_id TEXT, puuid TEXT, name TEXT, session_id INT, mode TEXT, champion TEXT,"
                " kills INT, deaths INT, assists INT, damage INT, win INT, pompes INT, ended_at REAL,"
                " PRIMARY KEY (match_id, puuid))")
    old.commit()
    old.close()
    conn = db._connect(str(path))
    assert "done_at" in {r["name"] for r in conn.execute("PRAGMA table_info(games)")}
    conn.close()


def test_json_migration(tmp_path, monkeypatch):
    files = {"CACHE_FILE": "c.json", "SESSION_FILE": "s.json", "STATE_FILE": "m.json"}
    for attr, name in files.items():
        monkeypatch.setattr(db, attr, str(tmp_path / name))
    monkeypatch.setattr(db, "DB_FILE", str(tmp_path / "mig.db"))
    (tmp_path / "c.json").write_text(json.dumps({
        "pZ|450": {"Kbar": 1, "Abar": 2, "Dbar": 3, "name": "Zed", "ts": time.time()},
        "AncienFormat": {"Kbar": 1},
    }))
    (tmp_path / "s.json").write_text(json.dumps({"Zed": 12}))
    (tmp_path / "m.json").write_text(json.dumps({
        "seeded_puuids": ["pZ"], "processed_match_ids": ["EUW1_9"],
        "recent_teams": {"EUW1_9": {"pF": "F"}, "EUW1_8": {"pF": "F"}},
    }))

    db.conn().close()
    db._conn = None
    assert db.get_cached_kda("pZ", 450) == {"Kbar": 1, "Abar": 2, "Dbar": 3}
    assert [(r["name"], r["total"]) for r in db.session_leaderboard()] == [("Zed", 12)]
    assert db.is_seeded("pZ") and db.is_processed("EUW1_9") and db.is_friend("pF")
    assert not (tmp_path / "c.json").exists() and (tmp_path / "c.json.migrated").exists()

    # Redémarrage : pas de second import.
    db.conn().close()
    db._conn = None
    assert [(r["name"], r["total"]) for r in db.session_leaderboard()] == [("Zed", 12)]


def test_known_players_only_owner_and_friends():
    db.set_cached_kda("pA", 450, {"Kbar": 1, "Abar": 1, "Dbar": 1}, "A")    # propriétaire
    db.record_team("EUW1_1", {"pB": "B", "pR": "Random"})
    db.record_team("EUW1_2", {"pB": "B"})                                    # B : pote ; Random : vu 1 fois
    assert set(db.known_players()) == {"A", "B"}
    assert db.find_player("random") is None

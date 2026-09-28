import time
from datetime import datetime
from zoneinfo import ZoneInfo

import achievements
import db
from pushups import calculate_pushups

AVG = {"Kbar": 10, "Abar": 20, "Dbar": 10}


def _result(puuid="pA", name="A", k=10, d=10, a=20, win=True, **extra):
    total, _, breakdown = calculate_pushups(k, d, a, name, AVG, win,
                                            loss_streak=extra.get("loss_streak", 0))
    return {"puuid": puuid, "name": name, "kills": k, "deaths": d, "assists": a, "win": win,
            "pompes": total, "damage": extra.pop("damage", 20000), "breakdown": breakdown, **extra}


def test_game_achievements():
    assert achievements.new_game_achievements(_result(d=0)) == ["intouchable"]
    assert achievements.new_game_achievements(_result(pentakills=1)) == ["pentakill"]
    assert achievements.new_game_achievements(_result(fb_kill=True)) == ["premier_sang"]
    assert achievements.new_game_achievements(_result(top_game_damage=True)) == ["carry"]
    assert achievements.new_game_achievements(_result(win=False, loss_streak=3)) == ["serie_noire"]
    assert achievements.new_game_achievements(_result(win_streak=5)) == ["inarretable"]
    assert achievements.new_game_achievements(_result(k=40)) == ["ange"]         # minimum de sa catégorie
    assert achievements.new_game_achievements(_result()) == []


def test_achievement_is_announced_once():
    r = _result(d=0)
    assert achievements.new_game_achievements(r) == ["intouchable"]
    assert achievements.new_game_achievements(r) == ["intouchable"]    # lecture seule tant que non enregistré
    assert db.unlock("pA", "intouchable", "EUW1_1")
    assert not db.unlock("pA", "intouchable", "EUW1_2")
    assert achievements.new_game_achievements(r) == []


def test_done_milestones():
    db.record_game("EUW1_1", "ARAM", time.time(), [{
        "puuid": "pA", "name": "A", "champion": "Jinx", "kills": 0, "deaths": 0, "assists": 0,
        "damage": 0, "win": True, "pompes": 120}])
    assert achievements.unlock_done_achievements("pA") == []          # pas encore validées
    db.mark_done("EUW1_1", "pA")
    assert achievements.unlock_done_achievements("pA") == ["centurion"]
    assert achievements.unlock_done_achievements("pA") == []


def test_season_records_need_enough_games():
    tz = ZoneInfo("Europe/Paris")
    now = datetime(2026, 6, 1, 20, 0, tzinfo=tz).timestamp()
    last_year = datetime(2025, 12, 31, 20, 0, tzinfo=tz).timestamp()
    db.record_game("EUW1_0", "ARAM", last_year, [{
        "puuid": "pA", "name": "A", "champion": "Jinx", "kills": 99, "deaths": 0, "assists": 0,
        "damage": 999999, "win": True, "pompes": 99}])
    for i in range(1, 5):
        db.record_game(f"EUW1_{i}", "ARAM", now - i * 3600, [{
            "puuid": "pA", "name": "A", "champion": "Jinx", "kills": 10, "deaths": 5, "assists": 5,
            "damage": 30000, "win": True, "pompes": 20}])
    best = [_result(name="B", k=12, damage=31000)]
    best[0]["pompes"] = 25

    # 4 parties dans l'année : trop tôt pour annoncer des records.
    assert achievements.season_records("EUW1_9", now, best) == []

    db.record_game("EUW1_5", "ARAM", now - 5 * 3600, [{
        "puuid": "pA", "name": "A", "champion": "Jinx", "kills": 10, "deaths": 5, "assists": 5,
        "damage": 30000, "win": True, "pompes": 20}])
    lines = achievements.season_records("EUW1_9", now, best)
    # L'année précédente ne compte pas (99 kills en 2025).
    assert lines == [
        "💀 **B** — record de pompes sur une partie : 25 pompes",
        "⚔️ **B** — record de kills sur une partie : 12 kills",
        "💥 **B** — record de dégâts sur une partie : 31k dégâts",
    ]

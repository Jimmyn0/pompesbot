"""
Persistance JSON et cache KDA avec TTL.
"""

import json
import os
import time
from typing import Optional

from config import CACHE_FILE, KDA_CACHE_TTL, SESSION_FILE


def _load_json(path: str) -> dict:
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_json(path: str, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


kda_cache:      dict = _load_json(CACHE_FILE)
session_totals: dict = _load_json(SESSION_FILE)


def get_cached_kda(player_name: str) -> Optional[dict]:
    entry = kda_cache.get(player_name)
    if not entry:
        return None
    if time.time() - entry.get("ts", 0) > KDA_CACHE_TTL:
        return None
    return {"Kbar": entry["Kbar"], "Abar": entry["Abar"], "Dbar": entry["Dbar"]}


def set_cached_kda(player_name: str, kba: dict) -> None:
    kda_cache[player_name] = {**kba, "ts": time.time()}
    _save_json(CACHE_FILE, kda_cache)


def invalidate_kda(player_name: str) -> bool:
    if player_name in kda_cache:
        del kda_cache[player_name]
        _save_json(CACHE_FILE, kda_cache)
        return True
    return False


def add_session_pompes(player_name: str, nb: int) -> int:
    session_totals[player_name] = session_totals.get(player_name, 0) + nb
    _save_json(SESSION_FILE, session_totals)
    return session_totals[player_name]


def reset_session() -> None:
    session_totals.clear()
    _save_json(SESSION_FILE, session_totals)

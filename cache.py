"""
Persistance JSON et cache KDA avec TTL.
"""

import json
import os
import time
from typing import Optional

from config import CACHE_FILE, KDA_CACHE_TTL, SESSION_FILE, STATE_FILE

MAX_PROCESSED_IDS = 1000


def _load_json(path: str) -> dict:
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_json(path: str, data: dict) -> None:
    """Écriture atomique : un crash en cours d'écriture ne corrompt pas le fichier."""
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


kda_cache:      dict = _load_json(CACHE_FILE)
session_totals: dict = _load_json(SESSION_FILE)
_state:         dict = _load_json(STATE_FILE)

seeded_puuids:       set[str]  = set(_state.get("seeded_puuids", []))
processed_match_ids: list[str] = _state.get("processed_match_ids", [])
_processed_set:      set[str]  = set(processed_match_ids)


def _kda_key(player_name: str, queue: int) -> str:
    return f"{player_name}|{queue}"


def get_cached_kda(player_name: str, queue: int) -> Optional[dict]:
    entry = kda_cache.get(_kda_key(player_name, queue))
    if not entry:
        return None
    if time.time() - entry.get("ts", 0) > KDA_CACHE_TTL:
        return None
    return {"Kbar": entry["Kbar"], "Abar": entry["Abar"], "Dbar": entry["Dbar"]}


def set_cached_kda(player_name: str, queue: int, kba: dict) -> None:
    kda_cache[_kda_key(player_name, queue)] = {**kba, "ts": time.time()}
    _save_json(CACHE_FILE, kda_cache)


def invalidate_kda(player_name: str) -> bool:
    keys = [k for k in kda_cache if k == player_name or k.startswith(f"{player_name}|")]
    for k in keys:
        del kda_cache[k]
    if keys:
        _save_json(CACHE_FILE, kda_cache)
    return bool(keys)


def get_session_total(player_name: str) -> int:
    return session_totals.get(player_name, 0)


def add_session_pompes(player_name: str, nb: int) -> int:
    session_totals[player_name] = session_totals.get(player_name, 0) + nb
    _save_json(SESSION_FILE, session_totals)
    return session_totals[player_name]


def reset_session() -> None:
    session_totals.clear()
    _save_json(SESSION_FILE, session_totals)


# --- État de détection des parties (survit aux redémarrages) ---

def _save_state() -> None:
    _save_json(STATE_FILE, {
        "seeded_puuids":       sorted(seeded_puuids),
        "processed_match_ids": processed_match_ids,
    })


def is_processed(match_id: str) -> bool:
    return match_id in _processed_set


def mark_processed(*match_ids: str) -> None:
    for mid in match_ids:
        if mid not in _processed_set:
            processed_match_ids.append(mid)
            _processed_set.add(mid)
    while len(processed_match_ids) > MAX_PROCESSED_IDS:
        _processed_set.discard(processed_match_ids.pop(0))
    _save_state()


def mark_seeded(puuid: str, match_ids: list[str]) -> None:
    seeded_puuids.add(puuid)
    mark_processed(*match_ids)

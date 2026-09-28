"""
Persistance JSON et cache KDA avec TTL.
"""

import json
import os
import time
from typing import Optional

from config import CACHE_FILE, FRIEND_LOOKBACK, FRIEND_MIN_GAMES, KDA_CACHE_TTL, SESSION_FILE, STATE_FILE

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
# match_id -> {puuid: pseudo} des coéquipiers du propriétaire, sur ses FRIEND_LOOKBACK dernières parties
recent_teams:        dict[str, dict[str, str]] = _state.get("recent_teams", {})


def _kda_key(puuid: str, queue: int) -> str:
    return f"{puuid}|{queue}"


def get_cached_kda(puuid: str, queue: int) -> Optional[dict]:
    entry = kda_cache.get(_kda_key(puuid, queue))
    if not entry:
        return None
    if time.time() - entry.get("ts", 0) > KDA_CACHE_TTL:
        return None
    return {"Kbar": entry["Kbar"], "Abar": entry["Abar"], "Dbar": entry["Dbar"]}


def set_cached_kda(puuid: str, queue: int, kba: dict, player_name: str) -> None:
    kda_cache[_kda_key(puuid, queue)] = {**kba, "name": player_name, "ts": time.time()}
    _save_json(CACHE_FILE, kda_cache)


def invalidate_kda(player_name: str) -> bool:
    name = player_name.lower()
    keys = [k for k, v in kda_cache.items() if str(v.get("name", "")).lower() == name]
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
        "recent_teams":        recent_teams,
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


def _match_order(match_id: str) -> int:
    """EUW1_7123456789 → 7123456789 (les IDs sont croissants dans le temps)."""
    try:
        return int(match_id.rsplit("_", 1)[1])
    except (IndexError, ValueError):
        return 0


def record_team(match_id: str, teammates: dict[str, str]) -> None:
    """Mémorise les coéquipiers du propriétaire sur une partie (fenêtre glissante)."""
    recent_teams[match_id] = teammates
    for old in sorted(recent_teams, key=_match_order)[:-FRIEND_LOOKBACK]:
        del recent_teams[old]
    _save_state()


def is_friend(puuid: str) -> bool:
    return sum(puuid in team for team in recent_teams.values()) >= FRIEND_MIN_GAMES


def known_friends() -> dict[str, tuple[str, int]]:
    """puuid -> (pseudo le plus récent, nb de parties ensemble)."""
    friends: dict[str, tuple[str, int]] = {}
    for mid in sorted(recent_teams, key=_match_order):
        for puuid, name in recent_teams[mid].items():
            friends[puuid] = (name, friends.get(puuid, ("", 0))[1] + 1)
    return {p: v for p, v in friends.items() if v[1] >= FRIEND_MIN_GAMES}


def mark_seeded(puuid: str, match_ids: list[str]) -> None:
    seeded_puuids.add(puuid)
    mark_processed(*match_ids)

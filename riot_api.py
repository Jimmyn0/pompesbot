"""
Couche d'accès à l'API Riot Games.
"""

import logging
from typing import Optional

import requests
from riotwatcher import ApiError, LolWatcher, RiotWatcher

from cache import get_cached_kda, set_cached_kda
from config import DEFAULT_KDA, KDA_SAMPLE_SIZE, REGION_V5, RIOT_API_KEY

log = logging.getLogger("PompesBot")

lol_watcher  = LolWatcher(RIOT_API_KEY)
riot_watcher = RiotWatcher(RIOT_API_KEY)

puuid_cache:            dict[str, str] = {}
last_processed_matches: dict[str, str] = {}


def get_puuid(game_name: str, tag_line: str) -> Optional[str]:
    key = f"{game_name}#{tag_line}".lower()
    if key in puuid_cache:
        return puuid_cache[key]
    try:
        user  = riot_watcher.account.by_riot_id(REGION_V5, game_name, tag_line)
        puuid = user.get("puuid")
        puuid_cache[key] = puuid
        log.info(f"PUUID récupéré pour {game_name}")
        return puuid
    except ApiError as e:
        log.error(f"PUUID {game_name}: {e}")
        return None


def fetch_aram_kda(puuid: str, count: int = KDA_SAMPLE_SIZE) -> Optional[dict]:
    try:
        match_ids = lol_watcher.match.matchlist_by_puuid(
            REGION_V5, puuid, queue=450, count=count
        )
    except ApiError as e:
        log.warning(f"matchlist ARAM: {e}")
        return None

    if not match_ids:
        return None

    total_k = total_d = total_a = 0
    valid = 0

    for mid in match_ids:
        try:
            detail = lol_watcher.match.by_id(REGION_V5, mid)
            for p in detail["info"]["participants"]:
                if p["puuid"] == puuid:
                    total_k += p.get("kills", 0)
                    total_d += p.get("deaths", 0)
                    total_a += p.get("assists", 0)
                    valid   += 1
                    break
        except ApiError:
            continue

    if valid == 0:
        return None

    return {
        "Kbar": round(total_k / valid, 2),
        "Abar": round(total_a / valid, 2),
        "Dbar": round(total_d / valid, 2),
    }


def get_player_kda_stats(player_name: str, puuid: str) -> dict:
    cached = get_cached_kda(player_name)
    if cached:
        return cached

    log.info(f"Calcul KDA moyen pour {player_name} ({KDA_SAMPLE_SIZE} parties)…")
    stats = fetch_aram_kda(puuid)
    if stats:
        set_cached_kda(player_name, stats)
        log.info(f"KDA {player_name}: K={stats['Kbar']} A={stats['Abar']} D={stats['Dbar']}")
        return stats

    log.warning(f"KDA indisponible pour {player_name}, fallback défaut")
    return DEFAULT_KDA.copy()


def check_new_match(puuid: str) -> Optional[str]:
    try:
        matches = lol_watcher.match.matchlist_by_puuid(REGION_V5, puuid, count=1)
        if not matches:
            return None
        last = matches[0]
        if puuid not in last_processed_matches:
            last_processed_matches[puuid] = last
            return None
        if last != last_processed_matches[puuid]:
            last_processed_matches[puuid] = last
            return last
        return None
    except ApiError:
        return None


def get_match_detail(match_id: str) -> Optional[dict]:
    try:
        return lol_watcher.match.by_id(REGION_V5, match_id)
    except ApiError as e:
        log.error(f"match detail {match_id}: {e}")
        return None


def get_first_blood(match_id: str) -> tuple[Optional[int], Optional[int]]:
    try:
        url     = f"https://europe.api.riotgames.com/lol/match/v5/matches/{match_id}/timeline"
        headers = {"X-Riot-Token": RIOT_API_KEY}
        data    = requests.get(url, headers=headers, timeout=10).json()
        for frame in data.get("info", {}).get("frames", []):
            for event in frame.get("events", []):
                if event.get("type") == "CHAMPION_KILL":
                    return event.get("killerId"), event.get("victimId")
    except Exception as e:
        log.warning(f"Timeline {match_id}: {e}")
    return None, None

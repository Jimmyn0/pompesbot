"""
Couche d'accès à l'API Riot Games (async, via aiohttp).

Toutes les requêtes passent par RiotClient, qui :
- respecte les limites de la clé (fenêtres glissantes, cf. RIOT_RATE_LIMITS) ;
- réessaie après un 429 (en-tête Retry-After), une erreur 5xx ou réseau ;
- ne lève jamais d'exception vers l'appelant : en cas d'échec, retourne None.
"""

import asyncio
import logging
import time
from collections import deque
from typing import Any
from urllib.parse import quote

import aiohttp

from config import (
    DEFAULT_KDA,
    KDA_SAMPLE_SIZE,
    REGION_V5,
    RIOT_API_KEY,
    RIOT_RATE_LIMITS,
)
from db import get_cached_kda, get_cached_puuid, set_cached_kda, set_cached_puuid

log = logging.getLogger("PompesBot")

MAX_RETRIES  = 4
BACKOFF_BASE = 2   # pause de BACKOFF_BASE ** essai secondes entre deux essais


class RateLimiter:
    """Fenêtres glissantes : [(nb_requêtes, secondes), ...]."""

    def __init__(self, limits: list[tuple[int, float]]) -> None:
        self.limits = limits
        self.history: deque[float] = deque()
        self.lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self.lock:
            while True:
                now = time.monotonic()
                longest = max(window for _, window in self.limits)
                while self.history and now - self.history[0] > longest:
                    self.history.popleft()

                wait = 0.0
                for count, window in self.limits:
                    recent = [t for t in self.history if now - t < window]
                    if len(recent) >= count:
                        wait = max(wait, window - (now - recent[-count]))
                if wait <= 0:
                    self.history.append(now)
                    return
                await asyncio.sleep(wait)


class RiotClient:
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self.limiter = RateLimiter(RIOT_RATE_LIMITS)
        self.session: aiohttp.ClientSession | None = None

    async def start(self) -> None:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                headers={"X-Riot-Token": self.api_key},
                timeout=aiohttp.ClientTimeout(total=15),
            )

    async def close(self) -> None:
        if self.session and not self.session.closed:
            await self.session.close()

    async def get(self, path: str, params: dict | None = None) -> Any | None:
        """GET https://{REGION_V5}.api.riotgames.com{path} — None si échec ou 404."""
        if self.session is None:
            await self.start()
        url = f"https://{REGION_V5}.api.riotgames.com{path}"

        for attempt in range(1, MAX_RETRIES + 1):
            await self.limiter.acquire()
            try:
                async with self.session.get(url, params=params) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    if resp.status == 404:
                        return None
                    if resp.status == 401:
                        log.error(f"Riot API 401 : clé absente ou invalide ({path})")
                        return None
                    if resp.status == 403:
                        # Clé expirée, ou donnée que Riot n'expose pas (ex. parties d'ARAM Mayhem).
                        log.warning(f"Riot API 403 : accès refusé ({path})")
                        return None
                    if resp.status == 429:
                        delay = float(resp.headers.get("Retry-After", 5))
                        log.warning(f"Rate limit Riot, pause {delay:.0f}s")
                        await asyncio.sleep(delay)
                        continue
                    if resp.status < 500:
                        log.error(f"Riot API {resp.status} sur {path}")
                        return None
                    log.warning(f"Riot API {resp.status} sur {path} (essai {attempt})")
            except (TimeoutError, aiohttp.ClientError) as e:
                log.warning(f"Erreur réseau Riot sur {path} (essai {attempt}) : {e!r}")
            await asyncio.sleep(BACKOFF_BASE ** attempt)

        log.error(f"Abandon après {MAX_RETRIES} essais : {path}")
        return None


client = RiotClient(RIOT_API_KEY)

puuid_cache: dict[str, str] = {}


async def get_puuid(game_name: str, tag_line: str) -> str | None:
    """PUUID (API) d'un Riot ID : mémoire, puis base, puis Riot (une seule fois par joueur)."""
    key = f"{game_name}#{tag_line}".lower()
    if key in puuid_cache:
        return puuid_cache[key]
    cached = get_cached_puuid(key)
    if cached:
        puuid_cache[key] = cached
        return cached
    data = await client.get(f"/riot/account/v1/accounts/by-riot-id/{quote(game_name, safe='')}/{quote(tag_line, safe='')}")
    if not data or "puuid" not in data:
        log.error(f"PUUID introuvable pour {game_name}#{tag_line}")
        return None
    puuid_cache[key] = data["puuid"]
    set_cached_puuid(key, data["puuid"])
    log.info(f"PUUID récupéré pour {game_name}")
    return data["puuid"]


async def get_recent_match_ids(
    puuid: str, count: int = 5, queue: int | None = None
) -> list[str] | None:
    params: dict[str, int] = {"count": count}
    if queue is not None:
        params["queue"] = queue
    return await client.get(f"/lol/match/v5/matches/by-puuid/{puuid}/ids", params)


async def get_match_detail(match_id: str) -> dict | None:
    return await client.get(f"/lol/match/v5/matches/{match_id}")


async def fetch_kda(puuid: str, queue: int, count: int = KDA_SAMPLE_SIZE) -> dict | None:
    match_ids = await get_recent_match_ids(puuid, count=count, queue=queue)
    if not match_ids:
        return None

    details = await asyncio.gather(*(get_match_detail(mid) for mid in match_ids))

    total_k = total_d = total_a = 0
    valid = 0
    for detail in details:
        if not detail:
            continue
        for p in detail["info"]["participants"]:
            if p["puuid"] == puuid:
                total_k += p.get("kills", 0)
                total_d += p.get("deaths", 0)
                total_a += p.get("assists", 0)
                valid   += 1
                break

    if valid == 0:
        return None

    return {
        "Kbar": round(total_k / valid, 2),
        "Abar": round(total_a / valid, 2),
        "Dbar": round(total_d / valid, 2),
    }


async def get_player_kda_stats(player_name: str, puuid: str, queue: int, mode: str = "ARAM") -> dict:
    cached = get_cached_kda(puuid, queue)
    if cached:
        return cached

    log.info(f"Calcul KDA moyen pour {player_name} (queue {queue}, {KDA_SAMPLE_SIZE} parties)…")
    stats = await fetch_kda(puuid, queue)
    if stats:
        set_cached_kda(puuid, queue, stats, player_name)
        log.info(f"KDA {player_name}: K={stats['Kbar']} A={stats['Abar']} D={stats['Dbar']}")
        return stats

    log.warning(f"KDA indisponible pour {player_name} (queue {queue}), fallback défaut")
    return DEFAULT_KDA.get(mode, DEFAULT_KDA["ARAM"]).copy()


async def get_first_blood(match_id: str) -> tuple[int | None, int | None]:
    data = await client.get(f"/lol/match/v5/matches/{match_id}/timeline")
    if not data:
        return None, None
    for frame in data.get("info", {}).get("frames", []):
        for event in frame.get("events", []):
            if event.get("type") == "CHAMPION_KILL":
                return event.get("killerId"), event.get("victimId")
    return None, None

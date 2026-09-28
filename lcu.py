"""
Lecture des parties depuis le client League installé sur le PC du bot (API locale « LCU »).

Riot n'expose pas certaines parties dans son API publique (notamment l'ARAM Mayhem / ARAM du
chaos : ni dans l'historique, ni par ID). Le client, lui, les a avec tout le détail. Ce module
lit son historique en lecture seule et convertit chaque partie au format match-v5, pour que
le reste du bot la traite comme une partie Riot.

Le client écrit son port et son mot de passe dans un fichier « lockfile » tant qu'il est ouvert.
Client fermé ou absent (Docker, autre PC) : toutes les fonctions renvoient None, sans erreur.
"""

import base64
import logging

import aiohttp

from champion_icons import champion_name
from config import LCU_LOCKFILES

log = logging.getLogger("PompesBot")

HISTORY_SIZE = 20   # le client ne garde qu'une vingtaine de parties


class LcuClient:
    def __init__(self, lockfiles: list[str]) -> None:
        self.lockfiles = lockfiles
        self.session: aiohttp.ClientSession | None = None
        self._credentials: tuple[str, str] | None = None   # (port, mot de passe)
        self._connected = False

    def _read_lockfile(self) -> tuple[str, str] | None:
        for path in self.lockfiles:
            try:
                with open(path, encoding="utf-8") as f:
                    _name, _pid, port, password, _proto = f.read().strip().split(":")
                return port, password
            except (OSError, ValueError):
                continue
        return None

    def _set_connected(self, connected: bool) -> None:
        if connected != self._connected:
            log.info("Client League détecté" if connected else "Client League fermé")
        self._connected = connected

    async def get(self, path: str) -> dict | None:
        """GET sur l'API locale du client ; None si le client est fermé ou si la requête échoue."""
        credentials = self._read_lockfile()
        if credentials is None:
            self._set_connected(False)
            return None
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                connector=aiohttp.TCPConnector(ssl=False),   # certificat auto-signé du client
                timeout=aiohttp.ClientTimeout(total=15),
            )
        port, password = credentials
        auth = base64.b64encode(f"riot:{password}".encode()).decode()
        try:
            async with self.session.get(f"https://127.0.0.1:{port}{path}",
                                        headers={"Authorization": f"Basic {auth}"}) as resp:
                self._set_connected(True)
                if resp.status != 200:
                    log.debug(f"Client League {resp.status} sur {path}")
                    return None
                return await resp.json()
        except (aiohttp.ClientError, TimeoutError) as e:
            # Lockfile resté après une fermeture brutale, ou client en cours de démarrage.
            log.debug(f"Client League injoignable : {e!r}")
            self._set_connected(False)
            return None

    async def close(self) -> None:
        if self.session and not self.session.closed:
            await self.session.close()


client = LcuClient(LCU_LOCKFILES)


async def current_riot_id() -> tuple[str, str] | None:
    """(pseudo, tag) du compte connecté au client, ou None si le client est fermé.

    On compare des Riot ID et pas des PUUID : l'API publique de Riot renvoie des PUUID
    chiffrés propres à chaque clé API, différents de ceux du client.
    """
    me = await client.get("/lol-summoner/v1/current-summoner")
    if not me or not me.get("gameName"):
        return None
    return me["gameName"], me.get("tagLine", "")


async def recent_games() -> list[dict]:
    """Résumés des dernières parties du compte connecté au client, de la plus récente à la plus ancienne."""
    data = await client.get(f"/lol-match-history/v1/products/lol/current-summoner/matches"
                            f"?begIndex=0&endIndex={HISTORY_SIZE}")
    return (data or {}).get("games", {}).get("games", [])


_details: dict[int, dict] = {}   # une partie terminée ne change plus : cache en mémoire


async def game_detail(game_id: int) -> dict | None:
    """Détail complet d'une partie (les 10 joueurs)."""
    if game_id not in _details:
        detail = await client.get(f"/lol-match-history/v1/games/{game_id}")
        if not detail:
            return None
        _details[game_id] = detail
    return _details[game_id]


async def first_blood(game_id: int) -> tuple[int | None, int | None]:
    """(tueur, victime) du premier kill, d'après la chronologie du client."""
    timeline = await client.get(f"/lol-match-history/v1/game-timelines/{game_id}")
    for frame in (timeline or {}).get("frames", []):
        for event in frame.get("events", []):
            if event.get("type") == "CHAMPION_KILL":
                return event.get("killerId"), event.get("victimId")
    return None, None


def match_id(game: dict) -> str:
    """Même format que les IDs Riot (EUW1_7995738556), pour partager la détection des doublons."""
    return f"{game.get('platformId', 'EUW1')}_{game['gameId']}"


async def to_match_info(detail: dict) -> dict:
    """Convertit une partie du client au format `info` de match-v5 utilisé par le bot.

    `puuid` est ici celui du client (non chiffré) ; l'appelant doit le remplacer par le PUUID
    de l'API Riot, à partir du Riot ID (cf. loop._to_api_puuids). Il reste dans `lcuPuuid`.
    """
    identities = {pi["participantId"]: pi["player"] for pi in detail["participantIdentities"]}
    participants = []
    for p in detail["participants"]:
        stats  = p["stats"]
        player = identities.get(p["participantId"], {})
        participants.append({
            "participantId":   p["participantId"],
            "puuid":           player.get("puuid", ""),
            "lcuPuuid":        player.get("puuid", ""),
            "riotIdGameName":  player.get("gameName") or player.get("summonerName") or "?",
            "riotIdTagline":   player.get("tagLine", ""),
            "teamId":          p["teamId"],
            "playerSubteamId": stats.get("playerSubteamId"),
            "championId":      p["championId"],
            "championName":    await champion_name(p["championId"]),
            "kills":           stats["kills"],
            "deaths":          stats["deaths"],
            "assists":         stats["assists"],
            "totalDamageDealtToChampions": stats["totalDamageDealtToChampions"],
            "win":             stats["win"],
            "pentaKills":      stats.get("pentaKills", 0),
        })
    return {
        "queueId":          detail["queueId"],
        "gameMode":         detail["gameMode"],
        "gameEndTimestamp": detail["gameCreation"] + detail["gameDuration"] * 1000,
        "participants":     participants,
    }


async def kda_samples(lcu_puuid: str, queue: int) -> dict[str, tuple[int, int, int, float]]:
    """K/D/A d'un joueur dans ce mode, par partie de l'historique du client où il apparaît.

    Retourne {match_id: (kills, morts, assists, fin de partie en secondes)}. `lcu_puuid` : PUUID
    du client (non chiffré). Le client ne donne que l'historique du compte connecté : pour un
    pote, ce sont les parties jouées ensemble.
    """
    samples: dict[str, tuple[int, int, int, float]] = {}
    for game in await recent_games():
        if game.get("queueId") != queue:
            continue
        detail = await game_detail(game["gameId"])
        if not detail:
            continue
        ids = {pi["participantId"]: pi["player"].get("puuid") for pi in detail["participantIdentities"]}
        ended = (detail["gameCreation"] + detail["gameDuration"] * 1000) / 1000
        for p in detail["participants"]:
            if ids.get(p["participantId"]) == lcu_puuid:
                s = p["stats"]
                samples[match_id(detail)] = (s["kills"], s["deaths"], s["assists"], ended)
    return samples

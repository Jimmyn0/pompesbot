"""
Tâche périodique de surveillance des parties.
"""

import asyncio
import logging
import time
from typing import Optional

import discord
from discord.ext import tasks

from cache import (
    _match_order,
    add_session_pompes,
    get_session_total,
    is_friend,
    is_processed,
    known_friends,
    mark_processed,
    mark_seeded,
    record_team,
    seeded_puuids,
)
from config import (
    ARENA_GAME_MODE,
    ARENA_LABEL,
    CATCHUP_MAX_AGE,
    FRIEND_LOOKBACK,
    OWNER,
    QUEUE_NAMES,
    RECENT_MATCHES_CHECKED,
    SCAN_INTERVAL_SECONDS,
)
from champion_icons import champion_icon
from embed_builder import SPECIAL_ICONS, build_embed
from pushups import calculate_pushups
from riot_api import (
    get_first_blood,
    get_match_detail,
    get_player_kda_stats,
    get_puuid,
    get_recent_match_ids,
)

log = logging.getLogger("PompesBot")

MAX_ATTEMPTS = 5
_failures: dict[str, int] = {}
_warmup_task: Optional[asyncio.Task] = None


def match_mode(info: dict) -> Optional[str]:
    """Libellé du mode suivi (ARAM, URF, Arena), ou None si la partie est hors scope."""
    if info.get("gameMode") == ARENA_GAME_MODE:
        return ARENA_LABEL
    return QUEUE_NAMES.get(info.get("queueId"))


async def _get_channel(bot, channel_id: int) -> Optional[discord.abc.Messageable]:
    channel = bot.get_channel(channel_id)
    if channel is None:
        try:
            channel = await bot.fetch_channel(channel_id)
        except discord.HTTPException as e:
            log.error(f"Salon {channel_id} inaccessible : {e}")
            return None
    return channel


def _team_key(info: dict) -> str:
    # En Arena, les équipes sont les duos (playerSubteamId), pas 100/200.
    return "playerSubteamId" if info.get("gameMode") == ARENA_GAME_MODE else "teamId"


def _display_name(p: dict) -> str:
    return p.get("riotIdGameName") or p.get("summonerName") or "?"


def _record_owner_team(match_id: str, info: dict, owner_puuid: str) -> None:
    """Enregistre les coéquipiers du propriétaire sur cette partie (sert à détecter ses potes).

    En Arena, seul le duo compte : on y recroise souvent les mêmes inconnus dans le lobby.
    Un pote déjà connu reste compté pour les pompes même s'il est dans un autre duo.
    """
    participants = info.get("participants", [])
    key   = _team_key(info)
    owner = next((p for p in participants if p.get("puuid") == owner_puuid), None)
    if owner is None:
        return
    record_team(match_id, {
        p["puuid"]: _display_name(p)
        for p in participants
        if p.get(key) == owner.get(key) and p.get("puuid") != owner_puuid
    })


async def _bootstrap_friends(owner_puuid: str) -> list[str]:
    """Premier lancement : lit les dernières parties du propriétaire pour connaître ses potes."""
    ids = await get_recent_match_ids(owner_puuid, count=FRIEND_LOOKBACK) or []
    details = await asyncio.gather(*(get_match_detail(mid) for mid in ids))
    for mid, detail in zip(ids, details):
        if detail:
            _record_owner_team(mid, detail.get("info", {}), owner_puuid)
    friends = known_friends()
    log.info(f"{len(friends)} pote(s) détecté(s) : {', '.join(n for n, _ in friends.values()) or '—'}")
    return ids


async def warm_kda_cache(owner_puuid: str) -> None:
    """Précalcule le KDA ARAM du propriétaire et de ses potes, pour ne pas retarder les embeds."""
    players = {owner_puuid: OWNER["name"], **{p: n for p, (n, _) in known_friends().items()}}
    for puuid, name in players.items():
        try:
            await get_player_kda_stats(name, puuid, 450)
        except Exception:
            log.exception(f"Préchauffage KDA échoué pour {name}")
    log.info("Cache KDA prêt")


async def _process_match(channel, match_id: str, owner_puuid: str) -> bool:
    """Traite une partie. Retourne False si elle doit être réessayée plus tard."""
    match_detail = await get_match_detail(match_id)
    if not match_detail:
        return False

    info  = match_detail.get("info", {})
    queue = info.get("queueId")
    mode  = match_mode(info)
    _record_owner_team(match_id, info, owner_puuid)
    if mode is None:
        log.info(f"Match {match_id} ignoré (queue {queue} hors scope)")
        return True

    end_ms = info.get("gameEndTimestamp") or 0
    if end_ms and time.time() - end_ms / 1000 > CATCHUP_MAX_AGE:
        log.info(f"Match {match_id} ignoré (trop ancien)")
        return True

    fb_killer_pid, fb_victim_pid = await get_first_blood(match_id)
    participants = info.get("participants", [])

    team_key = _team_key(info)
    top_by_team: dict = {}
    for p in participants:
        team = p.get(team_key)
        best = top_by_team.get(team)
        if best is None or p.get("totalDamageDealtToChampions", 0) > best.get("totalDamageDealtToChampions", 0):
            top_by_team[team] = p
    top_dmg_ids = {p["participantId"] for p in top_by_team.values()}

    results = []
    for p in participants:
        pu = p.get("puuid")
        if pu != owner_puuid and not is_friend(pu):
            continue

        p_name = _display_name(p)
        k      = p.get("kills",   0)
        d      = p.get("deaths",  0)
        a      = p.get("assists", 0)
        win    = p.get("win", False)
        pid    = p.get("participantId")

        is_fb_kill   = pid == fb_killer_pid
        is_fb_victim = pid == fb_victim_pid
        is_top_dmg   = pid in top_dmg_ids

        stats = await get_player_kda_stats(p_name, pu, queue, mode)
        nb_pompes, level_label = calculate_pushups(
            k, d, a, p_name, stats, win,
            fb_kill=is_fb_kill,
            fb_victim=is_fb_victim,
            top_damage=is_top_dmg,
        )

        icons = ""
        if is_fb_kill:   icons += SPECIAL_ICONS["fb_kill"]
        if is_fb_victim: icons += SPECIAL_ICONS["fb_victim"]
        if is_top_dmg:   icons += SPECIAL_ICONS["top_damage"]

        results.append({
            "name":          p_name,
            "champ":         await champion_icon(p.get("championId", 0), p.get("championName", "—")),
            "kills":         k,
            "deaths":        d,
            "assists":       a,
            "damage":        p.get("totalDamageDealtToChampions", 0),
            "level":         level_label,
            "win":           win,
            "team":          p.get(team_key),
            "pompes":        nb_pompes,
            "total_session": get_session_total(p_name) + nb_pompes,
            "icons":         icons,
        })

    if not results:
        return True

    embed = build_embed(results, match_id, mode)
    await channel.send(embed=embed)

    # Les totaux ne sont enregistrés qu'une fois l'embed posté (pas de double comptage en cas de retry).
    for r in results:
        add_session_pompes(r["name"], r["pompes"])
    return True


async def scan(bot, channel_id: int) -> None:
    channel = await _get_channel(bot, channel_id)
    if not channel:
        return

    log.debug("Scan des parties…")
    owner_puuid = await get_puuid(OWNER["name"], OWNER["tag"])
    if not owner_puuid:
        return

    global _warmup_task
    if owner_puuid not in seeded_puuids:
        # Premier lancement : on apprend les potes et on mémorise l'historique sans le poster.
        mark_seeded(owner_puuid, await _bootstrap_friends(owner_puuid))
    if _warmup_task is None:
        _warmup_task = asyncio.create_task(warm_kda_cache(owner_puuid))

    ids = await get_recent_match_ids(owner_puuid, count=RECENT_MATCHES_CHECKED)
    new_ids = [mid for mid in ids or [] if not is_processed(mid)]

    for match_id in sorted(new_ids, key=_match_order):
        log.info(f"Nouveau match {match_id}")
        try:
            done = await _process_match(channel, match_id, owner_puuid)
        except Exception:
            log.exception(f"Erreur pendant le traitement de {match_id}")
            done = False

        if done:
            _failures.pop(match_id, None)
            mark_processed(match_id)
            continue

        _failures[match_id] = _failures.get(match_id, 0) + 1
        if _failures[match_id] >= MAX_ATTEMPTS:
            log.error(f"Abandon du match {match_id} après {MAX_ATTEMPTS} essais")
            _failures.pop(match_id)
            mark_processed(match_id)


def make_league_loop(bot, channel_id: int):
    @tasks.loop(seconds=SCAN_INTERVAL_SECONDS)
    async def league_loop() -> None:
        # Aucune exception ne doit remonter : elle arrêterait la boucle définitivement.
        try:
            await scan(bot, channel_id)
        except Exception:
            log.exception("Erreur inattendue pendant le scan")

    @league_loop.before_loop
    async def before_league_loop() -> None:
        await bot.wait_until_ready()

    return league_loop

"""
Tâche périodique de surveillance des parties.
"""

import asyncio
import logging
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import discord
from discord.ext import tasks

import lcu
from achievements import new_game_achievements, season_records
from champion_icons import champion_icon
from config import (
    ARENA_GAME_MODE,
    ARENA_LABEL,
    CATCHUP_MAX_AGE,
    FRIEND_LOOKBACK,
    LCU_QUEUES,
    OWNER,
    QUEUE_NAMES,
    RECAP_HOUR,
    RECAP_WEEKDAY,
    RECENT_MATCHES_CHECKED,
    SCAN_INTERVAL_SECONDS,
    SESSION_IDLE_HOURS,
    TIMEZONE,
)
from db import (
    _match_order,
    current_streak,
    get_cached_kda,
    get_meta,
    get_session_total,
    is_friend,
    is_processed,
    is_seeded,
    known_friends,
    mark_processed,
    mark_seeded,
    record_game,
    record_team,
    rollover_if_idle,
    set_cached_kda,
    set_meta,
    unlock,
)
from embed_builder import SPECIAL_ICONS, build_embed
from pushups import calculate_pushups
from reports import session_summary_embed, weekly_recap_embed
from riot_api import (
    get_first_blood,
    get_match_detail,
    get_player_kda_stats,
    get_puuid,
    get_recent_match_ids,
)
from views import game_view

log = logging.getLogger("PompesBot")

MAX_ATTEMPTS = 5
_failures: dict[str, int] = {}
_warmup_task: asyncio.Task | None = None


def match_mode(info: dict) -> str | None:
    """Libellé du mode suivi (ARAM, URF, Arena), ou None si la partie est hors scope."""
    if info.get("gameMode") == ARENA_GAME_MODE:
        return ARENA_LABEL
    return QUEUE_NAMES.get(info.get("queueId"))


async def _get_channel(bot, channel_id: int) -> discord.abc.Messageable | None:
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
    for mid, detail in zip(ids, details, strict=True):
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


async def _close_idle_session(channel, now: float) -> None:
    """Clôt la session si elle est inactive depuis SESSION_IDLE_HOURS et poste son bilan."""
    closed = rollover_if_idle(now, SESSION_IDLE_HOURS * 3600)
    if closed is None:
        return
    log.info(f"Session {closed} clôturée (inactivité)")
    summary = session_summary_embed(closed)
    if summary:
        try:
            await channel.send(embed=summary)
        except discord.HTTPException as e:
            log.error(f"Bilan de session non posté : {e}")


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
    ended_at = end_ms / 1000 if end_ms else time.time()

    # Rattrapage après un arrêt du bot : une longue pause entre deux parties clôt aussi la session.
    await _close_idle_session(channel, ended_at)

    first_blood = await get_first_blood(match_id)
    return await post_match(channel, match_id, info, mode, ended_at, owner_puuid, first_blood)


async def post_match(
    channel,
    match_id: str,
    info: dict,
    mode: str,
    ended_at: float,
    owner_puuid: str,
    first_blood: tuple[int | None, int | None],
) -> bool:
    """Calcule les pompes d'une partie, poste l'embed et enregistre les résultats.

    Séparé de _process_match (récupération côté Riot) pour que /test_partie puisse y faire
    passer une partie générée.
    """
    fb_killer_pid, fb_victim_pid = first_blood
    queue        = info.get("queueId")
    participants = info.get("participants", [])

    team_key = _team_key(info)
    top_by_team: dict = {}
    for p in participants:
        team = p.get(team_key)
        best = top_by_team.get(team)
        if best is None or p.get("totalDamageDealtToChampions", 0) > best.get("totalDamageDealtToChampions", 0):
            top_by_team[team] = p
    top_dmg_ids = {p["participantId"] for p in top_by_team.values()}
    top_game_dmg_id = max(participants, key=lambda p: p.get("totalDamageDealtToChampions", 0),
                          default={}).get("participantId")

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

        # Série en cours dans la session, partie actuelle comprise.
        prev_win, prev_len = current_streak(pu)
        streak = prev_len + 1 if prev_win == win else 1

        stats = await get_player_kda_stats(p_name, pu, queue, mode)
        nb_pompes, level_label, breakdown = calculate_pushups(
            k, d, a, p_name, stats, win,
            fb_kill=is_fb_kill,
            fb_victim=is_fb_victim,
            top_damage=is_top_dmg,
            loss_streak=0 if win else streak,
            puuid=pu,
        )

        icons = ""
        if is_fb_kill:             icons += SPECIAL_ICONS["fb_kill"]
        if is_fb_victim:           icons += SPECIAL_ICONS["fb_victim"]
        if is_top_dmg:             icons += SPECIAL_ICONS["top_damage"]
        if breakdown["loss_streak"]: icons += SPECIAL_ICONS["loss_streak"]
        if breakdown["deathless"]:   icons += SPECIAL_ICONS["deathless"]

        results.append({
            "puuid":         pu,
            "pid":           pid,
            "name":          p_name,
            "champion":      p.get("championName", "—"),
            "champ":         await champion_icon(p.get("championId", 0), p.get("championName", "—")),
            "kills":         k,
            "deaths":        d,
            "assists":       a,
            "damage":        p.get("totalDamageDealtToChampions", 0),
            "level":         level_label,
            "win":           win,
            "team":          p.get(team_key),
            "pompes":        nb_pompes,
            "total_session": get_session_total(pu) + nb_pompes,
            "icons":         icons,
            "breakdown":     breakdown,
            "fb_kill":       is_fb_kill,
            "top_game_damage": pid == top_game_dmg_id,
            "pentakills":    p.get("pentaKills", 0),
            "loss_streak":   0 if win else streak,
            "win_streak":    streak if win else 0,
        })

    if not results:
        return True

    unlocked = {r["puuid"]: new_game_achievements(r) for r in results}
    records  = season_records(match_id, ended_at, results)
    embed = build_embed(results, match_id, mode, achievements=[
        (r["name"], code) for r in results for code in unlocked[r["puuid"]]
    ], records=records)
    await channel.send(embed=embed, view=game_view(match_id, results))

    # Résultats et succès enregistrés seulement une fois l'embed posté (pas de double comptage en cas de retry).
    record_game(match_id, mode, ended_at, results)
    for puuid, codes in unlocked.items():
        for code in codes:
            unlock(puuid, code, match_id)
    return True


async def scan(bot, channel_id: int) -> None:
    channel = await _get_channel(bot, channel_id)
    if not channel:
        return

    log.debug("Scan des parties…")
    await _close_idle_session(channel, time.time())
    owner_puuid = await get_puuid(OWNER["name"], OWNER["tag"])
    if not owner_puuid:
        return

    global _warmup_task
    if not is_seeded(owner_puuid):
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
        _after_attempt(match_id, done)

    # Parties que Riot n'expose pas (ARAM Mayhem) : lues depuis le client League du PC, s'il est ouvert.
    try:
        await _scan_client_games(channel, owner_puuid)
    except Exception:
        log.exception("Erreur pendant la lecture du client League")


def _after_attempt(match_id: str, done: bool) -> None:
    """Marque la partie traitée, ou compte l'échec (abandon après MAX_ATTEMPTS essais)."""
    if done:
        _failures.pop(match_id, None)
        mark_processed(match_id)
        return
    _failures[match_id] = _failures.get(match_id, 0) + 1
    if _failures[match_id] >= MAX_ATTEMPTS:
        log.error(f"Abandon du match {match_id} après {MAX_ATTEMPTS} essais")
        _failures.pop(match_id)
        mark_processed(match_id)


async def _client_match_info(detail: dict) -> dict:
    """Partie du client au format match-v5, avec les PUUID de l'API Riot.

    Le client utilise des PUUID bruts ; l'API Riot (et donc la base du bot) des PUUID chiffrés
    propres à la clé API. On retrouve ces derniers à partir du Riot ID, mais seulement pour
    l'équipe du propriétaire (ses potes y sont forcément) : les adversaires gardent un
    identifiant « lcu:… », sans appel à Riot. Chaque Riot ID n'est demandé qu'une fois (cf. get_puuid).
    """
    info = await lcu.to_match_info(detail)
    team_key = _team_key(info)
    owner = next((p for p in info["participants"]
                  if _is_owner((p["riotIdGameName"], p["riotIdTagline"]))), None)
    for p in info["participants"]:
        api_puuid = None
        same_team = owner is not None and p.get(team_key) == owner.get(team_key)
        if same_team and p["riotIdGameName"] and p["riotIdTagline"]:
            api_puuid = await get_puuid(p["riotIdGameName"], p["riotIdTagline"])
        p["puuid"] = api_puuid or f"lcu:{p['lcuPuuid']}"
    return info


def _is_owner(riot_id: tuple[str, str] | None) -> bool:
    return riot_id is not None and (riot_id[0].casefold(), riot_id[1].casefold()) == (
        OWNER["name"].casefold(), OWNER["tag"].casefold())


async def _process_client_game(channel, game_id: int, owner_puuid: str) -> bool:
    """Traite une partie lue dans le client League. False : à réessayer plus tard."""
    detail = await lcu.game_detail(game_id)
    if not detail:
        return False
    match_id = lcu.match_id(detail)
    info = await _client_match_info(detail)
    _record_owner_team(match_id, info, owner_puuid)
    mode = match_mode(info)
    if mode is None:
        return True

    ended_at = info["gameEndTimestamp"] / 1000
    if time.time() - ended_at > CATCHUP_MAX_AGE:
        log.info(f"Match {match_id} ignoré (trop ancien)")
        return True
    await _close_idle_session(channel, ended_at)

    # KDA de référence : l'API Riot n'a pas l'historique de ce mode, le client si.
    queue = info["queueId"]
    for p in info["participants"]:
        puuid = p["puuid"]
        if (puuid == owner_puuid or is_friend(puuid)) and get_cached_kda(puuid, queue) is None:
            baseline = await lcu.kda_baseline(p["lcuPuuid"], queue)
            if baseline:
                set_cached_kda(puuid, queue, baseline, p["riotIdGameName"])

    first_blood = await lcu.first_blood(game_id)
    return await post_match(channel, match_id, info, mode, ended_at, owner_puuid, first_blood)


async def _scan_client_games(channel, owner_puuid: str) -> None:
    if not _is_owner(await lcu.current_riot_id()):
        return   # client fermé, ou connecté à un autre compte
    games = [g for g in await lcu.recent_games() if g.get("queueId") in LCU_QUEUES]

    if get_meta("lcu_seeded") is None:
        # Première lecture du client : on apprend les potes sur son historique, sans rien poster.
        for game in games:
            detail = await lcu.game_detail(game["gameId"])
            if detail:
                _record_owner_team(lcu.match_id(detail), await _client_match_info(detail), owner_puuid)
        mark_processed(*(lcu.match_id(g) for g in games))
        set_meta("lcu_seeded", "1")
        friends = known_friends()
        log.info(f"Client League : {len(games)} partie(s) d'historique lues, "
                 f"{len(friends)} pote(s) : {', '.join(n for n, _ in friends.values()) or '—'}")
        return

    for game in sorted(games, key=lambda g: g["gameCreation"]):
        match_id = lcu.match_id(game)
        if is_processed(match_id):
            continue
        log.info(f"Nouvelle partie (client League) {match_id}")
        try:
            done = await _process_client_game(channel, game["gameId"], owner_puuid)
        except Exception:
            log.exception(f"Erreur pendant le traitement de {match_id}")
            done = False
        _after_attempt(match_id, done)


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


def recap_moment(now: datetime) -> datetime:
    """Moment du récap de la semaine en cours (ex. lundi 10 h)."""
    monday = (now - timedelta(days=now.weekday())).replace(hour=RECAP_HOUR, minute=0, second=0, microsecond=0)
    return monday + timedelta(days=RECAP_WEEKDAY)


async def post_weekly_recap(bot, channel_id: int, now: datetime) -> None:
    week = now.strftime("%G-W%V")
    last = get_meta("last_recap_week")
    if last is None:
        # Premier lancement : pas de récap rétroactif, le premier sera celui de la semaine prochaine.
        set_meta("last_recap_week", week)
        return
    moment = recap_moment(now)
    if last == week or now < moment:
        return

    channel = await _get_channel(bot, channel_id)
    if not channel:
        return
    embed = weekly_recap_embed((moment - timedelta(days=7)).timestamp(), moment)
    if embed:
        await channel.send(embed=embed)
        log.info("Récap hebdo posté")
    set_meta("last_recap_week", week)


def make_recap_loop(bot, channel_id: int):
    tz = ZoneInfo(TIMEZONE)

    # Vérification toutes les 15 min plutôt qu'à heure fixe : le récap part même si le bot
    # était éteint à l'heure prévue.
    @tasks.loop(minutes=15)
    async def recap_loop() -> None:
        try:
            await post_weekly_recap(bot, channel_id, datetime.now(tz))
        except Exception:
            log.exception("Erreur pendant le récap hebdo")

    @recap_loop.before_loop
    async def before_recap_loop() -> None:
        await bot.wait_until_ready()

    return recap_loop

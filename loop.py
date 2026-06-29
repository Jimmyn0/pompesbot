"""
Tâche périodique de surveillance des parties.
"""

import logging

from discord.ext import tasks

from cache import add_session_pompes
from config import PLAYERS_TO_TRACK, TARGET_QUEUE_IDS
from embed_builder import SPECIAL_ICONS, build_embed
from pushups import calculate_pushups
from riot_api import (
    check_new_match,
    get_first_blood,
    get_match_detail,
    get_puuid,
)

log = logging.getLogger("PompesBot")

processed_match_ids: set[str] = set()


def make_league_loop(bot, channel_id: int):
    @tasks.loop(seconds=30)
    async def league_loop() -> None:
        if not channel_id:
            return
        channel = bot.get_channel(channel_id)
        if not channel:
            return

        log.info("Scan des parties…")

        tracked: dict[str, dict] = {}
        for p in PLAYERS_TO_TRACK:
            puuid = get_puuid(p["name"], p["tag"])
            if puuid:
                tracked[puuid] = p

        for puuid, player in tracked.items():
            new_match_id = check_new_match(puuid)
            if not new_match_id or new_match_id in processed_match_ids:
                continue

            log.info(f"Nouveau match {new_match_id} pour {player['name']}")
            match_detail = get_match_detail(new_match_id)
            if not match_detail:
                continue

            info = match_detail.get("info", {})
            if info.get("queueId") not in TARGET_QUEUE_IDS:
                log.info("Match ignoré (mode hors scope)")
                processed_match_ids.add(new_match_id)
                continue

            fb_killer_pid, fb_victim_pid = get_first_blood(new_match_id)
            participants = info.get("participants", [])

            def top_dmg_id(team_id: int) -> int:
                team = [p for p in participants if p.get("teamId") == team_id]
                if not team:
                    return -1
                return max(team, key=lambda x: x.get("totalDamageDealtToChampions", 0))["participantId"]

            top100 = top_dmg_id(100)
            top200 = top_dmg_id(200)

            results = []
            for p in participants:
                pu = p.get("puuid")
                if pu not in tracked:
                    continue

                p_name = tracked[pu]["name"]
                k      = p.get("kills",   0)
                d      = p.get("deaths",  0)
                a      = p.get("assists", 0)
                champ  = p.get("championName", "—")
                win    = p.get("win", False)
                pid    = p.get("participantId")
                tid    = p.get("teamId", 100)
                dmg    = p.get("totalDamageDealtToChampions", 0)

                is_fb_kill   = pid == fb_killer_pid
                is_fb_victim = pid == fb_victim_pid
                is_top_dmg   = pid in (top100, top200)

                nb_pompes, level_label = calculate_pushups(
                    k, d, a, p_name, pu, win,
                    fb_kill=is_fb_kill,
                    fb_victim=is_fb_victim,
                    top_damage=is_top_dmg,
                )

                total_session = add_session_pompes(p_name, nb_pompes)

                icons = ""
                if is_fb_kill:   icons += SPECIAL_ICONS["fb_kill"]
                if is_fb_victim: icons += SPECIAL_ICONS["fb_victim"]
                if is_top_dmg:   icons += SPECIAL_ICONS["top_damage"]

                results.append({
                    "name":          p_name,
                    "champ":         champ,
                    "kills":         k,
                    "deaths":        d,
                    "assists":       a,
                    "damage":        dmg,
                    "level":         level_label,
                    "win":           win,
                    "team":          tid,
                    "pompes":        nb_pompes,
                    "total_session": total_session,
                    "icons":         icons,
                })

            if results:
                embed = build_embed(results, new_match_id)
                await channel.send(embed=embed)

            processed_match_ids.add(new_match_id)

    return league_loop

"""
PompesBot v2.0 — Discord ARAM Tracker
Refactorisé : auto-KDA, embed moderne, cache structuré, code modulaire
"""

import os
import json
import asyncio
import time
import logging
from math import floor
from typing import Optional

import discord
import requests
from discord.ext import commands, tasks
from riotwatcher import LolWatcher, RiotWatcher, ApiError
from dotenv import load_dotenv

# ──────────────────────────────────────────────
# 0. LOGGING
# ──────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("PompesBot")

# ──────────────────────────────────────────────
# 1. CONFIG
# ──────────────────────────────────────────────
load_dotenv()
DISCORD_TOKEN: str = os.getenv("DISCORD_TOKEN", "")
RIOT_API_KEY: str  = os.getenv("RIOT_API_KEY", "")
CHANNEL_ID: Optional[int] = int(os.getenv("DISCORD_CHANNEL_ID", 0)) or None

REGION_V5 = "europe"
REGION_V4 = "euw1"
TARGET_QUEUE_IDS = [450, 900, 1700]  # ARAM, URF, etc.

# Fichiers de cache persistants
CACHE_FILE   = "stats_cache.json"   # KDA moyens par joueur
SESSION_FILE = "session_totals.json" # Totaux de session

# Durée de validité du cache KDA (secondes) — 6 heures
KDA_CACHE_TTL = 6 * 3600
# Nb de parties récentes pour calculer la moyenne
KDA_SAMPLE_SIZE = 50

PLAYERS_TO_TRACK = [
    {"name": "Gold Ship",        "tag": "12BYN"},
    {"name": "iSPaRTaN v8",      "tag": "EUW"},
    {"name": "Bard est là",      "tag": "2384"},
    {"name": "Kerji",            "tag": "EUW"},
    {"name": "Matip",            "tag": "EUW"},
    {"name": "valquirit26",      "tag": "EUW"},
    {"name": "NigloCrediConso",  "tag": "333"},
    {"name": "Briçou",           "tag": "212"},
    {"name": "HysLerio",         "tag": "MDR"},
]

# Catégories de joueurs (peut être chargé depuis un JSON externe)
PLAYER_CATEGORIES = {
    "ELT": {
        "players":    ["Briçou", "Matip"],
        "base":       30,
        "min_pompes": 15,
        "mult_mort":  18,
        "mult_kill":  18,
    },
    "CNF": {
        "players":    ["Bard est là"],
        "base":       23,
        "min_pompes": 10,
        "mult_mort":  16,
        "mult_kill":  15,
    },
    "STD": {
        "players":    [],   # tout le reste
        "base":       15,
        "min_pompes": 5,
        "mult_mort":  12,
        "mult_kill":  10,
    },
}

DEFAULT_KDA = {"Kbar": 11.0, "Abar": 25.0, "Dbar": 11.0}

# ──────────────────────────────────────────────
# 2. ÉTAT GLOBAL (minimal)
# ──────────────────────────────────────────────
last_processed_matches: dict[str, str] = {}
processed_match_ids:    set[str]       = set()
puuid_cache:            dict[str, str] = {}

# ──────────────────────────────────────────────
# 3. CACHE KDA (persistant JSON)
# ──────────────────────────────────────────────
def _load_json(path: str) -> dict:
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def _save_json(path: str, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

kda_cache:      dict = _load_json(CACHE_FILE)   # {name: {Kbar, Abar, Dbar, ts}}
session_totals: dict = _load_json(SESSION_FILE)  # {name: int}

def get_cached_kda(player_name: str) -> Optional[dict]:
    entry = kda_cache.get(player_name)
    if not entry:
        return None
    if time.time() - entry.get("ts", 0) > KDA_CACHE_TTL:
        return None  # expiré
    return {"Kbar": entry["Kbar"], "Abar": entry["Abar"], "Dbar": entry["Dbar"]}

def set_cached_kda(player_name: str, kba: dict) -> None:
    kda_cache[player_name] = {**kba, "ts": time.time()}
    _save_json(CACHE_FILE, kda_cache)

# ──────────────────────────────────────────────
# 4. INITIALISATION DISCORD / RIOT
# ──────────────────────────────────────────────
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

lol_watcher  = LolWatcher(RIOT_API_KEY)
riot_watcher = RiotWatcher(RIOT_API_KEY)

# ──────────────────────────────────────────────
# 5. COUCHE API RIOT
# ──────────────────────────────────────────────
def get_puuid(game_name: str, tag_line: str) -> Optional[str]:
    key = f"{game_name}#{tag_line}".lower()
    if key in puuid_cache:
        return puuid_cache[key]
    try:
        user   = riot_watcher.account.by_riot_id(REGION_V5, game_name, tag_line)
        puuid  = user.get("puuid")
        puuid_cache[key] = puuid
        log.info(f"PUUID récupéré pour {game_name}")
        return puuid
    except ApiError as e:
        log.error(f"PUUID {game_name}: {e}")
        return None


def fetch_aram_kda(puuid: str, count: int = KDA_SAMPLE_SIZE) -> Optional[dict]:
    """
    Récupère les <count> dernières parties ARAM du joueur et calcule
    ses moyennes K/D/A. Retourne None si impossible.
    """
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
    valid   = 0

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
            continue  # on saute une partie en erreur, pas critique

    if valid == 0:
        return None

    return {
        "Kbar": round(total_k / valid, 2),
        "Abar": round(total_a / valid, 2),
        "Dbar": round(total_d / valid, 2),
    }


def get_player_kda_stats(player_name: str, puuid: str) -> dict:
    """
    Retourne les stats KDA pour un joueur :
    1. Depuis le cache si valide
    2. Depuis l'API Riot (50 parties ARAM)
    3. Fallback sur DEFAULT_KDA
    """
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
    """
    Retourne (killer_participant_id, victim_participant_id) du premier sang.
    """
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

# ──────────────────────────────────────────────
# 6. CALCUL DES POMPES
# ──────────────────────────────────────────────
def get_player_category(player_name: str) -> tuple[str, dict]:
    for label, cfg in PLAYER_CATEGORIES.items():
        if player_name in cfg["players"] or label == "STD":
            if player_name in cfg["players"] or label == "STD":
                return label, cfg
    return "STD", PLAYER_CATEGORIES["STD"]


def calculate_pushups(
    kills:      int,
    deaths:     int,
    assists:    int,
    player_name: str,
    puuid:      str,
    win:        bool,
    fb_kill:    bool = False,
    fb_victim:  bool = False,
    top_damage: bool = False,
) -> tuple[int, str]:
    """
    Retourne (nb_pompes, categorie_label).
    """
    # Catégorie
    cat_label, cfg = get_player_category(player_name)
    BASE        = cfg["base"]
    MIN_POMPES  = cfg["min_pompes"]
    MULT_MORT   = cfg["mult_mort"]
    MULT_KILL   = cfg["mult_kill"]
    BETA        = 0.5

    # Stats de référence (auto ou fallback)
    stats = get_player_kda_stats(player_name, puuid)
    Kbar, Abar, Dbar = stats["Kbar"], stats["Abar"], max(stats["Dbar"], 1)

    # Ratios
    score_reel  = kills  + BETA * assists
    score_moyen = max(Kbar + BETA * Abar, 1)
    ratio_off   = score_reel / score_moyen
    ratio_mort  = deaths / Dbar

    # Formule
    total  = BASE + (ratio_mort - 1) * MULT_MORT - (ratio_off - 1) * MULT_KILL
    if not win:
        total += 3

    # Bonus/malus spéciaux
    if fb_victim:  total += 1
    if fb_kill:    total -= 1
    if top_damage: total -= 1

    final = max(MIN_POMPES, floor(total))
    win_str = "Victoire" if win else "Défaite (+3)"
    log.debug(f"{player_name} [{cat_label}] ({win_str}): {final} pompes")
    return int(final), cat_label

# ──────────────────────────────────────────────
# 7. CONSTRUCTION DE L'EMBED DISCORD
# ──────────────────────────────────────────────
WIN_COLOR  = 0x2ECC71
LOSE_COLOR = 0xE74C3C

LEVEL_BADGE = {"ELT": "▲", "CNF": "●", "STD": "○"}

SPECIAL_ICONS = {
    "fb_kill":    "🩸🗡️",
    "fb_victim":  "🩸💀",
    "top_damage": "💥",
}

DMG_BAR_FILLED = "█"
DMG_BAR_EMPTY  = "░"
DMG_BAR_LEN    = 8


def damage_bar(dmg: int, max_dmg: int) -> str:
    if max_dmg == 0:
        filled = 0
    else:
        filled = round((dmg / max_dmg) * DMG_BAR_LEN)
    return DMG_BAR_FILLED * filled + DMG_BAR_EMPTY * (DMG_BAR_LEN - filled)


def kda_ratio(k: int, d: int, a: int) -> str:
    ratio = round((k + a) / max(d, 1), 2)
    return f"{ratio:.2f}"


def format_bonus_malus(icons: str) -> str:
    """
    Sépare les icônes FB du top damage par un espace pour éviter
    que les 3 emojis se collent quand c'est le même joueur.
    """
    fb_part  = ""
    dmg_part = ""
    if SPECIAL_ICONS["fb_kill"]    in icons: fb_part  += SPECIAL_ICONS["fb_kill"]
    if SPECIAL_ICONS["fb_victim"]  in icons: fb_part  += SPECIAL_ICONS["fb_victim"]
    if SPECIAL_ICONS["top_damage"] in icons: dmg_part  = SPECIAL_ICONS["top_damage"]
    parts = [p for p in [fb_part, dmg_part] if p]
    return "  ".join(parts)


def build_embed(results: list[dict], match_id: str) -> discord.Embed:
    """
    Scoreboard style post-game LoL.
    Colonnes : Joueur | Champion | KDA | Dmg | Pompes | ±
    """
    wins         = sum(1 for r in results if r["win"])
    color        = WIN_COLOR if wins >= len(results) / 2 else LOSE_COLOR
    result_label = "VICTOIRE" if wins >= len(results) / 2 else "DÉFAITE"
    result_icon  = "🏆" if wins >= len(results) / 2 else "💀"

    embed = discord.Embed(
        title=f"Fin de partie ARAM — {result_icon} {result_label}",
        color=color,
    )
    embed.set_footer(text=f"Match {match_id}")

    if not results:
        return embed

    # MVP = meilleur ratio KDA,  Flop = plus de pompes
    mvp   = max(results, key=lambda r: (r["kills"] + r["assists"]) / max(r["deaths"], 1))
    worst = max(results, key=lambda r: r["pompes"])
    if mvp is worst:
        worst = None

    # Tri par pompes croissant (meilleur en haut)
    sorted_results = sorted(results, key=lambda r: r["pompes"])

    # Colonnes : Joueur(13) Champ(10) KDA(9) Dmg(5) Pompes(4) ±
    header = "Joueur        Champ      KDA       Dmg   💪   ±\n"
    sep    = "─" * 52 + "\n"
    rows   = ""

    for r in sorted_results:
        tag = ""
        if r is mvp:     tag = " ★"
        elif r is worst: tag = " ▼"

        name_col  = (r["name"][:12] + tag).ljust(13)
        champ_col = r["champ"][:10].ljust(10)
        kda_col   = f"{r['kills']}/{r['deaths']}/{r['assists']}".ljust(9)
        dmg_col   = f"{r['damage'] // 1000}k".ljust(5)
        pompes    = str(r["pompes"]).ljust(4)
        bonus_str = format_bonus_malus(r["icons"])

        rows += f"{name_col} {champ_col} {kda_col} {dmg_col} {pompes} {bonus_str}\n"

    embed.add_field(name="Scores", value=f"```\n{header}{sep}{rows}```", inline=False)

    if len(results) > 1:
        embed.add_field(
            name="​",
            value="★ MVP  ▼ Flop  |  🩸🗡️ First Blood  🩸💀 First Death  |  💥 Top Dmg",
            inline=False,
        )

    return embed

# ──────────────────────────────────────────────
# 8. BOUCLE PRINCIPALE
# ──────────────────────────────────────────────
@tasks.loop(seconds=30)
async def league_loop() -> None:
    if not CHANNEL_ID:
        return
    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        return

    log.info("Scan des parties…")

    # Résolution PUUID
    tracked: dict[str, dict] = {}  # puuid -> player dict
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

        # First blood
        fb_killer_pid, fb_victim_pid = get_first_blood(new_match_id)

        participants = info.get("participants", [])

        # Top damage par équipe
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

            # Mise à jour session
            session_totals[p_name] = session_totals.get(p_name, 0) + nb_pompes
            _save_json(SESSION_FILE, session_totals)

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
                "total_session": session_totals[p_name],
                "icons":         icons,
            })

        if results:
            embed = build_embed(results, new_match_id)
            await channel.send(embed=embed)

        processed_match_ids.add(new_match_id)


# ──────────────────────────────────────────────
# 9. COMMANDES DISCORD
# ──────────────────────────────────────────────
@bot.command(name="session")
async def cmd_session(ctx: commands.Context) -> None:
    """Affiche le classement de pompes de la session."""
    if not session_totals:
        await ctx.send("Aucune donnée de session pour l'instant.")
        return

    lines = "\n".join(
        f"`#{i+1}` **{name}**  —  {total} pompes"
        for i, (name, total) in enumerate(
            sorted(session_totals.items(), key=lambda x: x[1], reverse=True)
        )
    )
    embed = discord.Embed(title="📊 Classement de session", description=lines, color=0xF1C40F)
    await ctx.send(embed=embed)


@bot.command(name="reset_session")
@commands.has_permissions(administrator=True)
async def cmd_reset_session(ctx: commands.Context) -> None:
    """Remet à zéro les totaux de session (admin)."""
    session_totals.clear()
    _save_json(SESSION_FILE, session_totals)
    await ctx.send("✅ Session réinitialisée.")


@bot.command(name="refresh_kda")
@commands.has_permissions(administrator=True)
async def cmd_refresh_kda(ctx: commands.Context, *, player_name: str) -> None:
    """Force le recalcul du KDA moyen pour un joueur."""
    # Supprime du cache pour forcer la mise à jour au prochain match
    if player_name in kda_cache:
        del kda_cache[player_name]
        _save_json(CACHE_FILE, kda_cache)
        await ctx.send(f"♻️ Cache KDA supprimé pour **{player_name}**. Recalcul au prochain match.")
    else:
        await ctx.send(f"Aucun cache trouvé pour **{player_name}**.")


# ──────────────────────────────────────────────
# 10. DÉMARRAGE
# ──────────────────────────────────────────────
@bot.event
async def on_ready() -> None:
    log.info(f"Bot connecté : {bot.user}")
    channel = bot.get_channel(CHANNEL_ID) if CHANNEL_ID else None
    if channel:
        await channel.send("🤖 **PompesBot v2.0** prêt ! Session démarrée. 💪")
    league_loop.start()


if __name__ == "__main__":
    if not all([DISCORD_TOKEN, RIOT_API_KEY, CHANNEL_ID]):
        log.error("Variables .env manquantes (DISCORD_TOKEN, RIOT_API_KEY, DISCORD_CHANNEL_ID)")
    else:
        bot.run(DISCORD_TOKEN)

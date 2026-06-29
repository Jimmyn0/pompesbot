"""
Construction de l'embed Discord post-partie.
"""

import discord

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
    filled = 0 if max_dmg == 0 else round((dmg / max_dmg) * DMG_BAR_LEN)
    return DMG_BAR_FILLED * filled + DMG_BAR_EMPTY * (DMG_BAR_LEN - filled)


def kda_ratio(k: int, d: int, a: int) -> str:
    ratio = round((k + a) / max(d, 1), 2)
    return f"{ratio:.2f}"


def _format_bonus_malus(icons: str) -> str:
    fb_part  = ""
    dmg_part = ""
    if SPECIAL_ICONS["fb_kill"]   in icons: fb_part  += SPECIAL_ICONS["fb_kill"]
    if SPECIAL_ICONS["fb_victim"] in icons: fb_part  += SPECIAL_ICONS["fb_victim"]
    if SPECIAL_ICONS["top_damage"] in icons: dmg_part  = SPECIAL_ICONS["top_damage"]
    parts = [p for p in [fb_part, dmg_part] if p]
    return "  ".join(parts)


def build_embed(results: list[dict], match_id: str) -> discord.Embed:
    """Scoreboard style post-game LoL. Colonnes : Joueur | Champion | KDA | Dmg | Pompes | ±"""
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

    mvp   = max(results, key=lambda r: (r["kills"] + r["assists"]) / max(r["deaths"], 1))
    worst = max(results, key=lambda r: r["pompes"])
    if mvp is worst:
        worst = None

    sorted_results = sorted(results, key=lambda r: r["pompes"])

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
        bonus_str = _format_bonus_malus(r["icons"])

        rows += f"{name_col} {champ_col} {kda_col} {dmg_col} {pompes} {bonus_str}\n"

    embed.add_field(name="Scores", value=f"```\n{header}{sep}{rows}```", inline=False)

    if len(results) > 1:
        embed.add_field(
            name="​",
            value="★ MVP  ▼ Flop  |  🩸🗡️ First Blood  🩸💀 First Death  |  💥 Top Dmg",
            inline=False,
        )

    return embed

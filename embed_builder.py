"""
Construction de l'embed Discord post-partie.
"""

import copy

import discord

WIN_COLOR  = 0x2ECC71
LOSE_COLOR = 0xE74C3C

SPECIAL_ICONS = {
    "fb_kill":    "🗡️",
    "fb_victim":  "💀",
    "top_damage": "💥",
}


def kda_ratio(k: int, d: int, a: int) -> str:
    ratio = round((k + a) / max(d, 1), 2)
    return f"{ratio:.2f}"


def build_embed(results: list[dict], match_id: str, queue_name: str = "ARAM") -> discord.Embed:
    """Scoreboard post-partie en trois colonnes : Joueur | KDA · Dmg | Pompes.

    Les colonnes sont des champs inline, alignés par Discord (un bloc de code ne peut pas
    afficher les icônes de champion, et y aligner des emojis est impossible).
    `r["champ"]` contient l'emoji du champion, ou son nom en repli.
    """
    wins         = sum(1 for r in results if r["win"])
    is_win       = wins >= len(results) / 2
    color        = WIN_COLOR if is_win else LOSE_COLOR
    result_label = "VICTOIRE" if is_win else "DÉFAITE"
    result_icon  = "🏆" if is_win else "💀"

    embed = discord.Embed(
        title=f"Fin de partie {queue_name} — {result_icon} {result_label}",
        color=color,
    )
    embed.set_footer(text=f"Match {match_id}")

    if not results:
        return embed

    mvp   = max(results, key=lambda r: (r["kills"] + r["assists"]) / max(r["deaths"], 1))
    worst = max(results, key=lambda r: r["pompes"])
    if mvp is worst:
        worst = None

    players, stats, pompes = [], [], []
    for r in sorted(results, key=lambda r: r["pompes"]):
        tag = ""
        if r is mvp:     tag = " ★"
        elif r is worst: tag = " ▼"

        players.append(f"{r['champ']} **{r['name'][:14]}**{tag}")
        stats.append(f"`{r['kills']}/{r['deaths']}/{r['assists']}` · {r['damage'] // 1000}k")
        pompes.append(f"**{r['pompes']}** {r['icons']}".rstrip())

    embed.add_field(name="Joueur",      value="\n".join(players), inline=True)
    embed.add_field(name="KDA · Dmg",   value="\n".join(stats),   inline=True)
    embed.add_field(name="💪 Pompes",   value="\n".join(pompes),  inline=True)

    legend = "🗡️ First Blood  💀 First Death  💥 Top Dmg  ✅ Pompes faites"
    if len(results) > 1:
        legend = "★ MVP  ▼ Flop  |  " + legend
    embed.add_field(name="​", value=legend, inline=False)

    return embed


def mark_player_done(embed: discord.Embed, player_name: str) -> discord.Embed:
    """Ajoute ✅ sur la ligne du joueur dans la colonne Pompes d'un embed déjà posté (copie modifiée)."""
    embed = discord.Embed.from_dict(copy.deepcopy(embed.to_dict()))   # Embed.copy() partage les champs
    fields = embed.fields
    if len(fields) < 3:
        return embed
    players = fields[0].value.splitlines()
    pompes  = fields[2].value.splitlines()
    for i, line in enumerate(players):
        if f"**{player_name[:14]}**" in line and i < len(pompes) and "✅" not in pompes[i]:
            pompes[i] += " ✅"
            embed.set_field_at(2, name=fields[2].name, value="\n".join(pompes), inline=True)
            break
    return embed

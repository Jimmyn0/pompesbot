"""
Embeds de bilan : fin de session, récap hebdomadaire, statistiques d'un joueur.
"""

import math
from datetime import datetime

import discord

from achievements import ACHIEVEMENTS
from db import count_games_since, leaderboard, session_bounds, session_leaderboard, worst_game_since

MEDALS = ["🥇", "🥈", "🥉"]


def _rank(i: int) -> str:
    return MEDALS[i] if i < len(MEDALS) else f"`#{i + 1}`"


def leaderboard_lines(board: list[dict]) -> str:
    """Une ligne par joueur : rang, pseudo, pompes dues, parties, pompes validées."""
    return "\n".join(
        f"{_rank(i)} **{r['name']}** — {r['total']} pompes · {r['n']} partie(s)"
        + (" · ✅ tout fait" if r["done"] >= r["total"] else f" · ✅ {r['done']}/{r['total']}")
        for i, r in enumerate(board)
    )


def _duration(start: float, end: float) -> str:
    minutes = int((end - start) // 60)
    return f"{minutes // 60} h {minutes % 60:02d}" if minutes >= 60 else f"{minutes} min"


def session_summary_embed(session_id: int) -> discord.Embed | None:
    board = session_leaderboard(session_id)
    if not board:
        return None
    first, last, n_games = session_bounds(session_id)
    embed = discord.Embed(title="🏁 Fin de session", description=leaderboard_lines(board), color=0x9B59B6)
    footer = f"{n_games} partie(s)"
    if first is not None and last > first:
        footer += f" sur {_duration(first, last)}"
    embed.set_footer(text=footer)
    return embed


def weekly_recap_embed(since: float, until: datetime) -> discord.Embed | None:
    board = leaderboard("ended_at >= ? AND match_id != 'MIGRATION'", (since,))
    if not board:
        return None

    start = datetime.fromtimestamp(since, until.tzinfo)
    embed = discord.Embed(
        title="📅 Récap de la semaine",
        description=f"Du {start:%d/%m} au {until:%d/%m} · {count_games_since(since)} partie(s)",
        color=0xE67E22,
    )
    embed.add_field(name="Classement", value=leaderboard_lines(board), inline=False)

    regular = [r for r in board if r["n"] >= 3] or board
    best = min(regular, key=lambda r: r["avg"])
    embed.add_field(name="😇 Le plus sage", value=f"**{best['name']}** — {best['avg']} pompes/partie", inline=True)

    worst = worst_game_since(since)
    if worst:
        embed.add_field(
            name="💀 Pire partie",
            value=(f"**{worst['name']}** — {worst['pompes']} pompes\n"
                   f"{worst['champion']} `{worst['kills']}/{worst['deaths']}/{worst['assists']}`"),
            inline=True,
        )

    debts = [(r["name"], r["total"] - r["done"]) for r in board if r["total"] > r["done"]]
    if debts:
        embed.add_field(
            name="🧾 Pompes pas encore faites",
            value="\n".join(f"**{n}** — {d}" for n, d in sorted(debts, key=lambda x: -x[1])),
            inline=False,
        )
    return embed


def stats_embed(stats: dict) -> discord.Embed:
    n = stats["n"]
    kda = (stats["k"] + stats["a"]) / max(stats["d"], 1)
    embed = discord.Embed(title=f"📈 Stats de {stats['name']}", color=0x1ABC9C)
    embed.add_field(name="Parties", value=f"{n} · {round(100 * stats['wins'] / n)} % de victoires", inline=True)
    embed.add_field(name="Pompes", value=f"{stats['total']} au total · {stats['avg']}/partie", inline=True)
    embed.add_field(name="✅ Faites", value=f"{stats['done']}/{stats['total']}", inline=True)
    embed.add_field(
        name="KDA moyen",
        value=f"`{stats['k'] / n:.1f}/{stats['d'] / n:.1f}/{stats['a'] / n:.1f}` · {kda:.2f}",
        inline=True,
    )
    fav, fav_n = stats["favorite"]
    embed.add_field(name="❤️ Champion favori", value=f"{fav} ({fav_n} parties)", inline=True)
    if stats["cursed"]:
        champ, avg, c_n = stats["cursed"]
        embed.add_field(name="🧿 Champion maudit", value=f"{champ} · {avg} pompes/partie ({c_n})", inline=True)

    w, b = stats["worst"], stats["best"]
    embed.add_field(
        name="💀 Pire partie",
        value=f"{w['pompes']} pompes · {w['champion']} `{w['kills']}/{w['deaths']}/{w['assists']}` ({w['mode']})",
        inline=False,
    )
    embed.add_field(
        name="😇 Meilleure partie",
        value=f"{b['pompes']} pompes · {b['champion']} `{b['kills']}/{b['deaths']}/{b['assists']}` ({b['mode']})",
        inline=False,
    )
    embed.set_footer(text=" · ".join(f"{m} : {c}" for m, c in sorted(stats["modes"].items(), key=lambda x: -x[1])))
    return embed


def _signed(value: float) -> str:
    return f"+{value:g}" if value > 0 else f"{value:g}".replace("-", "−")


def breakdown_embed(name: str, champion: str, mode: str, pompes: int, b: dict) -> discord.Embed:
    """Détail du calcul des pompes d'un joueur, affiché en message éphémère."""
    k, d, a = b["kda"]
    avg = b["avg"]
    lines = [
        f"**Niveau {b.get('level', b['category'])}** · {champion} · {mode}",
        "",
        f"Ta partie : `{k}/{d}/{a}` · ta moyenne : `{avg['K']:g}/{avg['D']:g}/{avg['A']:g}`",
        f"• Morts : {d} ÷ {avg['D']:g} = ×{b['ratio_mort']:g} de ta moyenne",
        f"• Kills + ½ assists : {b['score_reel']:g} ÷ {b['score_moyen']:g} = ×{b['ratio_off']:g} de ta moyenne",
        "",
    ]
    for label, value in b["steps"]:
        lines.append(f"`{_signed(value):>6}` {label}" if label != "Base" else f"`{value:>6g}` Base")
    lines.append(f"`{'= ' + format(b['raw'], 'g'):>6}` Sous-total")
    if b["floored"]:
        lines.append(f"`{b['min']:>6}` Minimum du niveau {b.get('level', b['category'])} (sous-total plus bas)")
    else:
        lines.append(f"`{math.floor(b['raw']):>6}` Arrondi à l'inférieur")
    if b["loss_streak"]:
        lines.append(f"` ×1,2 ` Série noire : {b['loss_streak']}e défaite d'affilée")
    if b["deathless"]:
        lines.append("`    −5` Intouchable : aucune mort")

    embed = discord.Embed(
        title=f"💪 {name} — {pompes} pompes",
        description="\n".join(lines),
        color=0x3498DB,
    )
    embed.set_footer(
        text=f"Mourir 2× plus que ta moyenne : +{b['mult_mort']} · "
             f"Faire 2× plus de kills + ½ assists que ta moyenne : −{b['mult_kill']}"
    )
    return embed


def achievements_embed(name: str, unlocked: list[tuple[str, float]]) -> discord.Embed:
    have = {code for code, _ in unlocked}
    lines = [
        f"{emoji} **{title}** — {cond}" if code in have else f"🔒 ~~{title}~~ — {cond}"
        for code, (emoji, title, cond) in ACHIEVEMENTS.items()
    ]
    return discord.Embed(
        title=f"🏅 Succès de {name} ({len(have)}/{len(ACHIEVEMENTS)})",
        description="\n".join(lines),
        color=0xF1C40F,
    )

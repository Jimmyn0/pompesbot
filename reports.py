"""
Embeds de bilan : fin de session, récap hebdomadaire, statistiques d'un joueur.
"""

from datetime import datetime
from typing import Optional

import discord

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


def session_summary_embed(session_id: int) -> Optional[discord.Embed]:
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


def weekly_recap_embed(since: float, until: datetime) -> Optional[discord.Embed]:
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

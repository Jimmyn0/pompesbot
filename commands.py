"""
Commandes Discord : !session, !potes, !reset_session, !refresh_kda
"""

import discord
from discord.ext import commands

from cache import invalidate_kda, known_friends, reset_session, session_totals
from config import FRIEND_LOOKBACK, FRIEND_MIN_GAMES


def setup(bot: commands.Bot) -> None:
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
        embed = discord.Embed(
            title="📊 Classement de session", description=lines, color=0xF1C40F
        )
        await ctx.send(embed=embed)

    @bot.command(name="potes")
    async def cmd_potes(ctx: commands.Context) -> None:
        """Liste les potes détectés automatiquement."""
        friends = sorted(known_friends().values(), key=lambda f: f[1], reverse=True)
        lines = "\n".join(f"**{name}** — {n} partie(s) ensemble" for name, n in friends)
        embed = discord.Embed(
            title="👥 Potes suivis",
            description=lines or "Aucun pour l'instant.",
            color=0x3498DB,
        )
        embed.set_footer(
            text=f"Coéquipiers vus au moins {FRIEND_MIN_GAMES} fois sur tes {FRIEND_LOOKBACK} dernières parties"
        )
        await ctx.send(embed=embed)

    @bot.command(name="reset_session")
    @commands.has_permissions(administrator=True)
    async def cmd_reset_session(ctx: commands.Context) -> None:
        """Remet à zéro les totaux de session (admin)."""
        reset_session()
        await ctx.send("✅ Session réinitialisée.")

    @bot.command(name="refresh_kda")
    @commands.has_permissions(administrator=True)
    async def cmd_refresh_kda(ctx: commands.Context, *, player_name: str) -> None:
        """Force le recalcul du KDA moyen pour un joueur."""
        if invalidate_kda(player_name):
            await ctx.send(
                f"♻️ Cache KDA supprimé pour **{player_name}**. Recalcul au prochain match."
            )
        else:
            await ctx.send(f"Aucun cache trouvé pour **{player_name}**.")

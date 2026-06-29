"""
Commandes Discord : !session, !reset_session, !refresh_kda
"""

import discord
from discord.ext import commands

from cache import invalidate_kda, reset_session, session_totals


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

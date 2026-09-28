"""
Slash commands : /session, /stats, /lier, /potes, /reset_session (admin), /refresh_kda (admin).
"""

from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from config import FRIEND_LOOKBACK, FRIEND_MIN_GAMES
from db import (
    find_player,
    invalidate_kda,
    kda_player_names,
    known_friends,
    known_players,
    link_discord,
    linked_player,
    player_stats,
    reset_session,
    session_leaderboard,
)
from reports import leaderboard_lines, stats_embed


async def player_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    return [
        app_commands.Choice(name=name, value=name)
        for name in sorted(known_players(), key=str.lower)
        if current.lower() in name.lower()
    ][:25]


def setup(bot: commands.Bot) -> None:
    tree = bot.tree

    @tree.command(name="session", description="Classement des pompes de la session en cours")
    async def cmd_session(interaction: discord.Interaction) -> None:
        board = session_leaderboard()
        if not board:
            await interaction.response.send_message("Aucune partie dans la session pour l'instant.")
            return
        embed = discord.Embed(
            title="📊 Classement de session", description=leaderboard_lines(board), color=0xF1C40F
        )
        await interaction.response.send_message(embed=embed)

    @tree.command(name="lier", description="Associe ton compte Discord à ton pseudo LoL")
    @app_commands.describe(joueur="Ton pseudo Riot (sans le #tag)")
    @app_commands.autocomplete(joueur=player_autocomplete)
    async def cmd_lier(interaction: discord.Interaction, joueur: str) -> None:
        found = find_player(joueur)
        if not found:
            await interaction.response.send_message(
                f"Je ne connais pas **{joueur}** : il faut avoir joué au moins une partie suivie par le bot.",
                ephemeral=True,
            )
            return
        puuid, name = found
        link_discord(interaction.user.id, puuid, name)
        await interaction.response.send_message(
            f"🔗 {interaction.user.mention} est maintenant lié à **{name}**. "
            "Tu peux valider tes pompes avec le bouton ✅ sous chaque partie."
        )

    @tree.command(name="stats", description="Statistiques de pompes d'un joueur")
    @app_commands.describe(joueur="Pseudo Riot (par défaut : le tien, via /lier)")
    @app_commands.autocomplete(joueur=player_autocomplete)
    async def cmd_stats(interaction: discord.Interaction, joueur: Optional[str] = None) -> None:
        if joueur:
            found = find_player(joueur)
        else:
            found = linked_player(interaction.user.id)
            if not found:
                await interaction.response.send_message(
                    "Précise un joueur, ou lie ton compte avec `/lier` pour voir tes propres stats.",
                    ephemeral=True,
                )
                return
        stats = player_stats(found[0]) if found else None
        if not stats:
            await interaction.response.send_message(
                f"Aucune partie enregistrée pour **{joueur or found[1]}**.", ephemeral=True
            )
            return
        await interaction.response.send_message(embed=stats_embed(stats))

    @tree.command(name="potes", description="Liste les potes détectés automatiquement")
    async def cmd_potes(interaction: discord.Interaction) -> None:
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
        await interaction.response.send_message(embed=embed)

    @tree.command(name="reset_session", description="Clôt la session en cours (l'historique est conservé)")
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    async def cmd_reset_session(interaction: discord.Interaction) -> None:
        reset_session()
        await interaction.response.send_message("✅ Session clôturée. La prochaine partie en ouvre une nouvelle.")

    @tree.command(name="refresh_kda", description="Force le recalcul du KDA moyen d'un joueur")
    @app_commands.describe(joueur="Pseudo Riot du joueur (sans le #tag)")
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    async def cmd_refresh_kda(interaction: discord.Interaction, joueur: str) -> None:
        if invalidate_kda(joueur):
            await interaction.response.send_message(
                f"♻️ Cache KDA supprimé pour **{joueur}**. Recalcul à sa prochaine partie."
            )
        else:
            await interaction.response.send_message(f"Aucun cache trouvé pour **{joueur}**.", ephemeral=True)

    @cmd_refresh_kda.autocomplete("joueur")
    async def joueur_autocomplete(
        interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        return [
            app_commands.Choice(name=name, value=name)
            for name in kda_player_names()
            if current.lower() in name.lower()
        ][:25]

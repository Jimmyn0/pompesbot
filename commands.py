"""
Slash commands : /session, /stats, /succes, /lier, /difficulte, /potes, /reset_session (admin), /refresh_kda (admin).
"""

import discord
from discord import app_commands
from discord.ext import commands

from config import FRIEND_LOOKBACK, FRIEND_MIN_GAMES, LEVELS, PLAYER_CATEGORIES, level_label
from db import (
    achievements_of,
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
    set_level,
)
from pushups import get_player_category
from reports import achievements_embed, leaderboard_lines, stats_embed


def _level_choices() -> list[app_commands.Choice[str]]:
    return [
        app_commands.Choice(
            name=f"{level_label(code)} (base {PLAYER_CATEGORIES[code]['base']}, "
                 f"minimum {PLAYER_CATEGORIES[code]['min_pompes']})",
            value=code,
        )
        for code in LEVELS
    ]


def _level_line(code: str) -> str:
    cfg = PLAYER_CATEGORIES[code]
    return (f"**{level_label(code)}** — base {cfg['base']}, minimum {cfg['min_pompes']}, "
            f"morts +{cfg['mult_mort']}, kills −{cfg['mult_kill']}")


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
    @app_commands.describe(joueur="Ton pseudo Riot (sans le #tag)",
                           difficulte="Ton niveau (modifiable ensuite avec /difficulte)")
    @app_commands.autocomplete(joueur=player_autocomplete)
    @app_commands.choices(difficulte=_level_choices())
    async def cmd_lier(interaction: discord.Interaction, joueur: str, difficulte: str | None = None) -> None:
        found = find_player(joueur)
        if not found:
            await interaction.response.send_message(
                f"Je ne connais pas **{joueur}** : il faut avoir joué au moins une partie suivie par le bot.",
                ephemeral=True,
            )
            return
        puuid, name = found
        link_discord(interaction.user.id, puuid, name)
        if difficulte in PLAYER_CATEGORIES:
            set_level(puuid, difficulte, name)
        level = get_player_category(name, puuid)[0]
        await interaction.response.send_message(
            f"🔗 {interaction.user.mention} est maintenant lié à **{name}**, niveau **{level_label(level)}**. "
            "Tu peux valider tes pompes avec le bouton ✅ sous chaque partie, "
            "et changer de niveau avec `/difficulte`."
        )

    @tree.command(name="difficulte", description="Voir ou changer ton niveau de difficulté")
    @app_commands.describe(niveau="Nouveau niveau (vide : afficher le niveau actuel)",
                           joueur="Changer le niveau d'un autre joueur (admin)")
    @app_commands.choices(niveau=_level_choices())
    @app_commands.autocomplete(joueur=player_autocomplete)
    async def cmd_difficulte(interaction: discord.Interaction, niveau: str | None = None,
                             joueur: str | None = None) -> None:
        if niveau is not None and niveau not in PLAYER_CATEGORIES:
            await interaction.response.send_message(f"Niveau inconnu : {niveau}.", ephemeral=True)
            return
        mine = linked_player(interaction.user.id)
        if joueur:
            found = find_player(joueur)
            if not found:
                await interaction.response.send_message(f"Je ne connais pas **{joueur}**.", ephemeral=True)
                return
            perms = getattr(interaction.user, "guild_permissions", None)
            if niveau and found != mine and not (perms and perms.administrator):
                await interaction.response.send_message(
                    "Seul un admin peut changer le niveau d'un autre joueur.", ephemeral=True)
                return
        else:
            found = mine
            if not found:
                await interaction.response.send_message(
                    "Lie d'abord ton compte avec `/lier`, ou précise un joueur.", ephemeral=True)
                return

        puuid, name = found
        if niveau is None:
            current = get_player_category(name, puuid)[0]
            embed = discord.Embed(
                title=f"🏋️ Niveau de {name} : {level_label(current)}",
                description="\n".join(_level_line(code) for code in LEVELS),
                color=0xE67E22,
            )
            embed.set_footer(text="Changer : /difficulte niveau:… (s'applique aux parties suivantes)")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        set_level(puuid, niveau, name)
        await interaction.response.send_message(
            f"🏋️ **{name}** passe au niveau **{level_label(niveau)}** : {_level_line(niveau).split(' — ')[1]}. "
            "S'applique à partir de la prochaine partie."
        )

    @tree.command(name="stats", description="Statistiques de pompes d'un joueur")
    @app_commands.describe(joueur="Pseudo Riot (par défaut : le tien, via /lier)")
    @app_commands.autocomplete(joueur=player_autocomplete)
    async def cmd_stats(interaction: discord.Interaction, joueur: str | None = None) -> None:
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
        embed = stats_embed(stats)
        embed.description = f"Niveau **{level_label(get_player_category(stats['name'], found[0])[0])}**"
        await interaction.response.send_message(embed=embed)

    @tree.command(name="succes", description="Succès débloqués par un joueur")
    @app_commands.describe(joueur="Pseudo Riot (par défaut : le tien, via /lier)")
    @app_commands.autocomplete(joueur=player_autocomplete)
    async def cmd_succes(interaction: discord.Interaction, joueur: str | None = None) -> None:
        found = find_player(joueur) if joueur else linked_player(interaction.user.id)
        if not found:
            await interaction.response.send_message(
                f"Je ne connais pas **{joueur}**." if joueur
                else "Précise un joueur, ou lie ton compte avec `/lier` pour voir tes succès.",
                ephemeral=True,
            )
            return
        puuid, name = found
        await interaction.response.send_message(embed=achievements_embed(name, achievements_of(puuid)))

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

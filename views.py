"""
Bouton « ✅ J'ai fait mes pompes » sous chaque embed de fin de partie.

C'est un DynamicItem : l'ID de la partie est encodé dans le custom_id, donc le bouton
reste fonctionnel après un redémarrage du bot (cf. bot.add_dynamic_items dans main.py).
"""

import re

import discord

from db import linked_player, mark_done
from embed_builder import mark_player_done


class DoneButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"pompes:done:(?P<match_id>[A-Za-z0-9_]+)",
):
    def __init__(self, match_id: str) -> None:
        super().__init__(
            discord.ui.Button(
                label="J'ai fait mes pompes",
                emoji="✅",
                style=discord.ButtonStyle.success,
                custom_id=f"pompes:done:{match_id}",
            )
        )
        self.match_id = match_id

    @classmethod
    async def from_custom_id(
        cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match[str], /
    ) -> "DoneButton":
        return cls(match["match_id"])

    async def callback(self, interaction: discord.Interaction) -> None:
        linked = linked_player(interaction.user.id)
        if not linked:
            await interaction.response.send_message(
                "Lie d'abord ton compte Discord à ton pseudo LoL avec `/lier`.", ephemeral=True
            )
            return

        puuid, name = linked
        status, pompes, game_name = mark_done(self.match_id, puuid)
        if status == "absent":
            await interaction.response.send_message(
                f"**{name}** ne fait pas partie de cette partie.", ephemeral=True
            )
        elif status == "deja":
            await interaction.response.send_message("Déjà validé ✅", ephemeral=True)
        else:
            embed = mark_player_done(interaction.message.embeds[0], game_name)
            await interaction.response.edit_message(embed=embed)
            await interaction.followup.send(f"💪 Bien joué, {pompes} pompes validées !", ephemeral=True)


def done_view(match_id: str) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    view.add_item(DoneButton(match_id))
    return view

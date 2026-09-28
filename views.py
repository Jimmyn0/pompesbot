"""
Boutons sous l'embed de fin de partie :
- un bouton par joueur (icône du champion + pseudo) : détail du calcul de ses pompes, en privé ;
- « ✅ J'ai fait mes pompes ».

Ce sont des DynamicItem : l'ID de la partie est encodé dans le custom_id, donc les boutons
restent fonctionnels après un redémarrage du bot (cf. bot.add_dynamic_items dans main.py).
"""

import re

import discord

from achievements import label as achievement_label
from achievements import unlock_done_achievements
from db import get_breakdown, linked_player, mark_done
from embed_builder import display_order, mark_player_done
from reports import breakdown_embed

MAX_DETAIL_BUTTONS = 20   # 4 rangées de 5 ; la 5e rangée est pour ✅


class DetailButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"pompes:detail:(?P<match_id>[A-Za-z0-9_]+):(?P<pid>\d+)",
):
    def __init__(self, match_id: str, participant_id: int, label: str = "Détail",
                 emoji: str | None = None, row: int | None = None) -> None:
        super().__init__(
            discord.ui.Button(
                label=label,
                emoji=emoji,
                style=discord.ButtonStyle.secondary,
                custom_id=f"pompes:detail:{match_id}:{participant_id}",
                row=row,
            )
        )
        self.match_id = match_id
        self.participant_id = participant_id

    @classmethod
    async def from_custom_id(
        cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match[str], /
    ) -> "DetailButton":
        return cls(match["match_id"], int(match["pid"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        game = get_breakdown(self.match_id, self.participant_id)
        if not game:
            await interaction.response.send_message("Détail indisponible pour cette partie.", ephemeral=True)
            return
        embed = breakdown_embed(game["name"], game["champion"], game["mode"], game["pompes"], game["breakdown"])
        await interaction.response.send_message(embed=embed, ephemeral=True)


class DoneButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"pompes:done:(?P<match_id>[A-Za-z0-9_]+)",
):
    def __init__(self, match_id: str, row: int | None = None) -> None:
        super().__init__(
            discord.ui.Button(
                label="J'ai fait mes pompes",
                emoji="✅",
                style=discord.ButtonStyle.success,
                custom_id=f"pompes:done:{match_id}",
                row=row,
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
            unlocked = unlock_done_achievements(puuid)
            if unlocked:
                await interaction.followup.send(
                    f"🏅 **{game_name}** débloque " + ", ".join(f"**{achievement_label(c)}**" for c in unlocked) + " !"
                )


def _button_face(r: dict) -> tuple[str, str | None]:
    """(libellé, emoji) du bouton d'un joueur : icône du champion si c'est un emoji Discord."""
    champ = r.get("champ", "")
    if champ.startswith("<:"):
        return r["name"][:40], champ
    return f"{r.get('champion', champ)} · {r['name']}"[:80], None


def game_view(match_id: str, results: list[dict]) -> discord.ui.View:
    """Boutons de détail (dans l'ordre de l'embed) puis ✅."""
    view = discord.ui.View(timeout=None)
    for i, r in enumerate(display_order(results)[:MAX_DETAIL_BUTTONS]):
        label, emoji = _button_face(r)
        view.add_item(DetailButton(match_id, r["pid"], label=label, emoji=emoji, row=i // 5))
    view.add_item(DoneButton(match_id, row=4))
    return view

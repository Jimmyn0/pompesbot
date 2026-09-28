"""
PompesBot v2.0 — point d'entrée.
"""

import logging

import discord
from discord.ext import commands

import champion_icons
from commands import setup as setup_commands
from config import CHANNEL_ID, DISCORD_TOKEN, RIOT_API_KEY
from loop import make_league_loop, make_recap_loop
from riot_api import client as riot_client
from views import DetailButton, DoneButton

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("PompesBot")


class PompesBot(commands.Bot):
    def __init__(self) -> None:
        # Slash commands uniquement : l'intent privilégié message_content n'est plus nécessaire.
        super().__init__(command_prefix=commands.when_mentioned, intents=discord.Intents.default())
        self.league_loop = make_league_loop(self, CHANNEL_ID)
        self.recap_loop  = make_recap_loop(self, CHANNEL_ID)
        self._announced = False

    async def setup_hook(self) -> None:
        # Appelé une seule fois (contrairement à on_ready, rappelé à chaque reconnexion).
        await riot_client.start()
        await champion_icons.setup(self)
        setup_commands(self)
        self.add_dynamic_items(DoneButton, DetailButton)  # boutons des embeds déjà postés, après redémarrage
        await self._sync_commands()
        self.league_loop.start()
        self.recap_loop.start()

    async def _sync_commands(self) -> None:
        """Enregistre les slash commands sur le serveur du salon (disponibles immédiatement)."""
        try:
            channel = await self.fetch_channel(CHANNEL_ID)
            guild = discord.Object(id=channel.guild.id)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            log.info(f"{len(synced)} slash command(s) synchronisée(s) sur le serveur {channel.guild.id}")
        except (discord.HTTPException, AttributeError) as e:
            log.error(f"Synchronisation des slash commands impossible : {e!r}")

    async def on_ready(self) -> None:
        log.info(f"Bot connecté : {self.user}")
        if self._announced:
            return
        self._announced = True
        channel = self.get_channel(CHANNEL_ID)
        if channel:
            await channel.send("🤖 **PompesBot v2.0** prêt ! Session démarrée. 💪")

    async def close(self) -> None:
        self.league_loop.cancel()
        self.recap_loop.cancel()
        await riot_client.close()
        await super().close()


if __name__ == "__main__":
    if not all([DISCORD_TOKEN, RIOT_API_KEY, CHANNEL_ID]):
        log.error("Variables .env manquantes (DISCORD_TOKEN, RIOT_API_KEY, DISCORD_CHANNEL_ID)")
    else:
        PompesBot().run(DISCORD_TOKEN, log_handler=None)

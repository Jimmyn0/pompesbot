"""
PompesBot v2.0 — point d'entrée.
"""

import logging

import discord
from discord.ext import commands

from commands import setup as setup_commands
from config import CHANNEL_ID, DISCORD_TOKEN, RIOT_API_KEY
from loop import make_league_loop
from riot_api import client as riot_client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("PompesBot")


class PompesBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)
        self.league_loop = make_league_loop(self, CHANNEL_ID)
        self._announced = False

    async def setup_hook(self) -> None:
        # Appelé une seule fois (contrairement à on_ready, rappelé à chaque reconnexion).
        await riot_client.start()
        setup_commands(self)
        self.league_loop.start()

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
        await riot_client.close()
        await super().close()


if __name__ == "__main__":
    if not all([DISCORD_TOKEN, RIOT_API_KEY, CHANNEL_ID]):
        log.error("Variables .env manquantes (DISCORD_TOKEN, RIOT_API_KEY, DISCORD_CHANNEL_ID)")
    else:
        PompesBot().run(DISCORD_TOKEN, log_handler=None)

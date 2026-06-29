"""
PompesBot v2.0 — point d'entrée.
"""

import logging

import discord
from discord.ext import commands

from commands import setup as setup_commands
from config import CHANNEL_ID, DISCORD_TOKEN, RIOT_API_KEY
from loop import make_league_loop

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("PompesBot")

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

setup_commands(bot)
league_loop = make_league_loop(bot, CHANNEL_ID)


@bot.event
async def on_ready() -> None:
    log.info(f"Bot connecté : {bot.user}")
    channel = bot.get_channel(CHANNEL_ID) if CHANNEL_ID else None
    if channel:
        await channel.send("🤖 **PompesBot v2.0** prêt ! Session démarrée. 💪")
    league_loop.start()


if __name__ == "__main__":
    if not all([DISCORD_TOKEN, RIOT_API_KEY, CHANNEL_ID]):
        log.error("Variables .env manquantes (DISCORD_TOKEN, RIOT_API_KEY, DISCORD_CHANNEL_ID)")
    else:
        bot.run(DISCORD_TOKEN)

"""
test_embed.py — Prévisualisation de l'embed sans lancer de partie
Lance avec : python test_embed.py
"""

import os
import discord
from discord.ext import commands
from dotenv import load_dotenv

from app2_2 import build_embed, session_totals, SPECIAL_ICONS

load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID    = int(os.getenv("DISCORD_CHANNEL_ID", 0))

FAKE_MATCH_ID = "EUW1_TEST123456789"

# Tous dans la même équipe (team 100), victoire
FAKE_RESULTS = [
    {
        "name":          "Player One",
        "champ":         "Jinx",
        "kills":         18, "deaths": 4,  "assists": 12,
        "damage":        52340,
        "level":         "STD",
        "win":           True,
        "team":          100,
        "pompes":        8,
        "total_session": 8,
        "icons":         SPECIAL_ICONS["fb_kill"] + SPECIAL_ICONS["top_damage"],
    },
    {
        "name":          "Player Five",
        "champ":         "Garen",
        "kills":         9,  "deaths": 7,  "assists": 21,
        "damage":        28900,
        "level":         "ELT",
        "win":           True,
        "team":          100,
        "pompes":        22,
        "total_session": 22,
        "icons":         "",
    },
    {
        "name":          "Player Three",
        "champ":         "Bard",
        "kills":         3,  "deaths": 9,  "assists": 34,
        "damage":        14200,
        "level":         "CNF",
        "win":           True,
        "team":          100,
        "pompes":        18,
        "total_session": 18,
        "icons":         "",
    },
    {
        "name":          "Player Four",
        "champ":         "Zed",
        "kills":         6,  "deaths": 14, "assists": 8,
        "damage":        31100,
        "level":         "STD",
        "win":           True,
        "team":          100,
        "pompes":        35,
        "total_session": 35,
        "icons":         SPECIAL_ICONS["fb_victim"],
    },
    {
        "name":          "Player Nine",
        "champ":         "Lux",
        "kills":         11, "deaths": 11, "assists": 17,
        "damage":        41800,
        "level":         "STD",
        "win":           True,
        "team":          100,
        "pompes":        19,
        "total_session": 19,
        "icons":         "",
    },
]

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"Bot connecté : {bot.user}")
    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        print(f"❌ Channel {CHANNEL_ID} introuvable. Vérifie DISCORD_CHANNEL_ID dans .env")
        await bot.close()
        return

    embed = build_embed(FAKE_RESULTS, FAKE_MATCH_ID)
    await channel.send(embed=embed)
    print("✅ Embed envoyé !")
    await bot.close()

if __name__ == "__main__":
    if not DISCORD_TOKEN or not CHANNEL_ID:
        print("❌ Manque DISCORD_TOKEN ou DISCORD_CHANNEL_ID dans .env")
    else:
        bot.run(DISCORD_TOKEN)

"""
Configuration centrale — constantes, variables d'environnement, liste de joueurs.
Les joueurs et catégories sont chargés depuis players.json (non versionné).
Copiez players.example.json → players.json et remplissez vos pseudos.
"""

import json
import os
import sys
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN: str        = os.getenv("DISCORD_TOKEN", "")
RIOT_API_KEY: str         = os.getenv("RIOT_API_KEY", "")
CHANNEL_ID: Optional[int] = int(os.getenv("DISCORD_CHANNEL_ID", 0)) or None

REGION_V5 = "europe"
REGION_V4 = "euw1"
TARGET_QUEUE_IDS = [450, 900, 1700]  # ARAM, URF, etc.

CACHE_FILE    = "stats_cache.json"
SESSION_FILE  = "session_totals.json"
PLAYERS_FILE  = "players.json"

KDA_CACHE_TTL   = 6 * 3600
KDA_SAMPLE_SIZE = 50

_players_path = os.path.join(os.path.dirname(__file__), PLAYERS_FILE)
if not os.path.exists(_players_path):
    print(f"[ERREUR] {PLAYERS_FILE} introuvable. Copiez players.example.json → players.json.")
    sys.exit(1)

with open(_players_path, "r", encoding="utf-8") as _f:
    _players_data = json.load(_f)

PLAYERS_TO_TRACK: list[dict]  = _players_data["PLAYERS_TO_TRACK"]
PLAYER_CATEGORIES: dict       = _players_data["PLAYER_CATEGORIES"]

DEFAULT_KDA = {"Kbar": 11.0, "Abar": 25.0, "Dbar": 11.0}

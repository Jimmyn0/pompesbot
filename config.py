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

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

load_dotenv(os.path.join(BASE_DIR, ".env"))

DISCORD_TOKEN: str        = os.getenv("DISCORD_TOKEN", "")
RIOT_API_KEY: str         = os.getenv("RIOT_API_KEY", "")
CHANNEL_ID: Optional[int] = int(os.getenv("DISCORD_CHANNEL_ID", 0)) or None

REGION_V5 = "europe"
REGION_V4 = "euw1"

QUEUE_NAMES = {
    450: "ARAM",
    900: "URF",
}
# L'Arena change de queueId selon les saisons (1700, 1710, 1740, 1750…) :
# on la reconnaît par son gameMode plutôt que par sa queue.
ARENA_GAME_MODE = "CHERRY"
ARENA_LABEL     = "Arena"

# Limites de la clé Riot (dev et personal key) : 20 req/1s et 100 req/2min.
RIOT_RATE_LIMITS: list[tuple[int, float]] = [(20, 1.0), (100, 120.0)]

SCAN_INTERVAL_SECONDS = 30
RECENT_MATCHES_CHECKED = 5            # parties récentes vérifiées par joueur à chaque scan
CATCHUP_MAX_AGE        = 12 * 3600    # au redémarrage, ignore les parties plus anciennes

CACHE_FILE    = os.path.join(BASE_DIR, "stats_cache.json")
SESSION_FILE  = os.path.join(BASE_DIR, "session_totals.json")
STATE_FILE    = os.path.join(BASE_DIR, "match_state.json")
PLAYERS_FILE  = os.path.join(BASE_DIR, "players.json")

KDA_CACHE_TTL   = 6 * 3600
KDA_SAMPLE_SIZE = 50

if not os.path.exists(PLAYERS_FILE):
    print("[ERREUR] players.json introuvable. Copiez players.example.json → players.json.")
    sys.exit(1)

with open(PLAYERS_FILE, "r", encoding="utf-8") as _f:
    _players_data = json.load(_f)

PLAYERS_TO_TRACK: list[dict]  = _players_data["PLAYERS_TO_TRACK"]
PLAYER_CATEGORIES: dict       = _players_data["PLAYER_CATEGORIES"]
DEFAULT_CATEGORY              = "STD"

if DEFAULT_CATEGORY not in PLAYER_CATEGORIES:
    print(f"[ERREUR] players.json : la catégorie {DEFAULT_CATEGORY} est obligatoire.")
    sys.exit(1)

# KDA moyen de repli par mode, si l'historique du joueur est indisponible.
DEFAULT_KDA = {
    "ARAM":  {"Kbar": 11.0, "Abar": 25.0, "Dbar": 11.0},
    "URF":   {"Kbar": 12.0, "Abar": 15.0, "Dbar": 9.0},
    "Arena": {"Kbar": 7.0,  "Abar": 5.0,  "Dbar": 6.0},  # estimation grossière
}

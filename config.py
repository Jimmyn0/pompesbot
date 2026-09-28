"""
Configuration centrale — constantes, variables d'environnement, liste de joueurs.
Le propriétaire et les catégories sont chargés depuis players.json (non versionné).
Copiez players.example.json → players.json et remplissez votre Riot ID.
"""

import json
import os
import sys

from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

load_dotenv(os.path.join(BASE_DIR, ".env"))

DISCORD_TOKEN: str        = os.getenv("DISCORD_TOKEN", "")
RIOT_API_KEY: str         = os.getenv("RIOT_API_KEY", "")
CHANNEL_ID: int | None    = int(os.getenv("DISCORD_CHANNEL_ID", 0)) or None

REGION_V5 = "europe"
REGION_V4 = "euw1"

QUEUE_NAMES = {
    450:  "ARAM",
    2400: "ARAM Mayhem",
    900:  "URF",
    1900: "URF",
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

# Dossier des données (players.json, base SQLite) : le dossier du bot par défaut,
# /data dans l'image Docker, un dossier temporaire dans les tests.
DATA_DIR = os.getenv("POMPESBOT_DATA_DIR", BASE_DIR)

# Mode test (POMPESBOT_DEV=1) : active /test_partie, qui génère de fausses parties, et poste dans
# DEV_CHANNEL_ID s'il est défini. Refusé sur les données de production (dossier du bot).
def dev_mode_enabled(flag: str | None, data_dir: str, base_dir: str) -> bool:
    same_dir = os.path.normcase(os.path.abspath(data_dir)) == os.path.normcase(os.path.abspath(base_dir))
    return flag == "1" and not same_dir


DEV_MODE = dev_mode_enabled(os.getenv("POMPESBOT_DEV"), DATA_DIR, BASE_DIR)
if DEV_MODE and os.getenv("DEV_CHANNEL_ID"):
    CHANNEL_ID = int(os.environ["DEV_CHANNEL_ID"])

DB_FILE       = os.path.join(DATA_DIR, "pompesbot.db")
PLAYERS_FILE  = os.path.join(DATA_DIR, "players.json")
# Anciens fichiers JSON, importés dans la base au premier lancement (cf. db._migrate_json)
CACHE_FILE    = os.path.join(DATA_DIR, "stats_cache.json")
SESSION_FILE  = os.path.join(DATA_DIR, "session_totals.json")
STATE_FILE    = os.path.join(DATA_DIR, "match_state.json")

# Défis
LOSS_STREAK_THRESHOLD  = 3     # à partir de la 3e défaite d'affilée dans la session…
LOSS_STREAK_MULTIPLIER = 1.2   # …les pompes de la partie sont multipliées par 1,2
DEATHLESS_BONUS        = 5     # partie sans mourir : -5 pompes (peut passer sous le minimum, pas sous 0)
WIN_STREAK_ACHIEVEMENT = 5     # succès « Inarrêtable » : 5 victoires d'affilée dans la session
RECORD_MIN_GAMES       = 5     # records de la saison annoncés après 5 parties dans l'année

SESSION_IDLE_HOURS = 6    # sans partie pendant ce délai, la session est clôturée et son bilan posté

TIMEZONE     = "Europe/Paris"
RECAP_WEEKDAY = 0         # récap hebdo le lundi (0 = lundi)…
RECAP_HOUR    = 10        # …à 10 h, heure de Paris

FRIEND_LOOKBACK  = 40   # parties récentes du propriétaire prises en compte
FRIEND_MIN_GAMES = 2    # un coéquipier vu au moins N fois dans cette fenêtre est un pote

KDA_CACHE_TTL   = 6 * 3600
KDA_SAMPLE_SIZE = 20   # 21 requêtes par joueur et par mode (limite clé : 100 req / 2 min)

if not os.path.exists(PLAYERS_FILE):
    print(f"[ERREUR] {PLAYERS_FILE} introuvable. Copiez players.example.json → players.json.")
    sys.exit(1)

with open(PLAYERS_FILE, encoding="utf-8") as _f:
    _players_data = json.load(_f)

# Seul le compte du propriétaire (celui qui lance le bot) est suivi ; ses potes sont
# détectés automatiquement parmi ses coéquipiers (cf. FRIEND_MIN_GAMES).
OWNER: dict             = _players_data["OWNER"]
PLAYER_CATEGORIES: dict = _players_data["PLAYER_CATEGORIES"]
DEFAULT_CATEGORY        = "STD"

if DEFAULT_CATEGORY not in PLAYER_CATEGORIES:
    print(f"[ERREUR] players.json : la catégorie {DEFAULT_CATEGORY} est obligatoire.")
    sys.exit(1)

# KDA moyen de repli par mode, si l'historique du joueur est indisponible.
DEFAULT_KDA = {
    "ARAM":  {"Kbar": 11.0, "Abar": 25.0, "Dbar": 11.0},
    "ARAM Mayhem": {"Kbar": 13.0, "Abar": 27.0, "Dbar": 12.0},  # estimation
    "URF":   {"Kbar": 12.0, "Abar": 15.0, "Dbar": 9.0},
    "Arena": {"Kbar": 7.0,  "Abar": 5.0,  "Dbar": 6.0},  # estimation grossière
}

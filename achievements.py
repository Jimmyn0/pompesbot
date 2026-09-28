"""
Succès (débloqués une seule fois par joueur) et records de la saison.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from config import LOSS_STREAK_THRESHOLD, RECORD_MIN_GAMES, TIMEZONE, WIN_STREAK_ACHIEVEMENT
from db import done_total, has_achievement, season_record, unlock

# code -> (emoji, nom, condition)
ACHIEVEMENTS: dict[str, tuple[str, str, str]] = {
    "intouchable":  ("🛡️", "Intouchable",  "Finir une partie sans mourir"),
    "pentakill":    ("🖐️", "Pentakill",    "Réussir un pentakill"),
    "premier_sang": ("🗡️", "Premier sang", "Faire le first blood"),
    "carry":        ("💥", "Carry",        "Infliger le plus de dégâts de toute la partie"),
    "serie_noire":  ("🌧️", "Série noire",  f"Perdre {LOSS_STREAK_THRESHOLD} parties d'affilée dans une session"),
    "inarretable":  ("🔥", "Inarrêtable",  f"Gagner {WIN_STREAK_ACHIEVEMENT} parties d'affilée dans une session"),
    "ange":         ("😇", "Ange gardien", "Ne faire que le minimum de pompes de sa catégorie"),
    "centurion":    ("💯", "Centurion",    "Valider 100 pompes au total"),
    "machine":      ("🏋️", "Machine",      "Valider 1000 pompes au total"),
}

DONE_MILESTONES = [(100, "centurion"), (1000, "machine")]

RECORDS = [
    # (colonne, emoji, libellé, unité)
    ("pompes", "💀", "de pompes sur une partie", "pompes"),
    ("kills",  "⚔️", "de kills sur une partie",  "kills"),
    ("damage", "💥", "de dégâts sur une partie", "dégâts"),
]


def label(code: str) -> str:
    emoji, name, _ = ACHIEVEMENTS[code]
    return f"{emoji} {name}"


def new_game_achievements(r: dict) -> list[str]:
    """Succès obtenus par un joueur sur cette partie et pas encore débloqués (lecture seule).

    L'enregistrement (db.unlock) se fait après l'envoi de l'embed, pour qu'un échec Discord
    suivi d'un nouvel essai annonce bien le succès.
    """
    b = r["breakdown"]
    earned = []
    if r["deaths"] == 0:                              earned.append("intouchable")
    if r.get("pentakills", 0) > 0:                    earned.append("pentakill")
    if r.get("fb_kill"):                              earned.append("premier_sang")
    if r.get("top_game_damage"):                      earned.append("carry")
    if r.get("loss_streak", 0) >= LOSS_STREAK_THRESHOLD: earned.append("serie_noire")
    if r.get("win_streak", 0) >= WIN_STREAK_ACHIEVEMENT: earned.append("inarretable")
    if r["pompes"] == b["min"] and not b["deathless"]: earned.append("ange")
    return [code for code in earned if not has_achievement(r["puuid"], code)]


def unlock_done_achievements(puuid: str) -> list[str]:
    """Succès liés aux pompes validées (après un clic sur ✅)."""
    total = done_total(puuid)
    return [code for threshold, code in DONE_MILESTONES if total >= threshold and unlock(puuid, code)]


def season_start(ended_at: float) -> float:
    """1er janvier de l'année de la partie, heure de Paris."""
    tz = ZoneInfo(TIMEZONE)
    year = datetime.fromtimestamp(ended_at, tz).year
    return datetime(year, 1, 1, tzinfo=tz).timestamp()


def season_records(match_id: str, ended_at: float, results: list[dict]) -> list[str]:
    """Records de la saison battus par cette partie (lignes prêtes à afficher)."""
    since = season_start(ended_at)
    lines = []
    for column, emoji, what, unit in RECORDS:
        best = max(results, key=lambda r: r[column])
        previous, n_games = season_record(column, since, match_id)
        if n_games >= RECORD_MIN_GAMES and best[column] > previous:
            value = f"{best[column] // 1000}k {unit}" if column == "damage" else f"{best[column]} {unit}"
            lines.append(f"{emoji} **{best['name']}** — record {what} : {value}")
    return lines

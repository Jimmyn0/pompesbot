"""
Calcul du nombre de pompes par joueur après une partie.
"""

import logging
from math import floor

from config import PLAYER_CATEGORIES
from riot_api import get_player_kda_stats

log = logging.getLogger("PompesBot")


def get_player_category(player_name: str) -> tuple[str, dict]:
    for label, cfg in PLAYER_CATEGORIES.items():
        if player_name in cfg["players"] or label == "STD":
            return label, cfg
    return "STD", PLAYER_CATEGORIES["STD"]


def calculate_pushups(
    kills:       int,
    deaths:      int,
    assists:     int,
    player_name: str,
    puuid:       str,
    win:         bool,
    fb_kill:     bool = False,
    fb_victim:   bool = False,
    top_damage:  bool = False,
) -> tuple[int, str]:
    """Retourne (nb_pompes, categorie_label)."""
    cat_label, cfg = get_player_category(player_name)
    BASE       = cfg["base"]
    MIN_POMPES = cfg["min_pompes"]
    MULT_MORT  = cfg["mult_mort"]
    MULT_KILL  = cfg["mult_kill"]
    BETA       = 0.5

    stats = get_player_kda_stats(player_name, puuid)
    Kbar, Abar, Dbar = stats["Kbar"], stats["Abar"], max(stats["Dbar"], 1)

    score_reel  = kills  + BETA * assists
    score_moyen = max(Kbar + BETA * Abar, 1)
    ratio_off   = score_reel / score_moyen
    ratio_mort  = deaths / Dbar

    total = BASE + (ratio_mort - 1) * MULT_MORT - (ratio_off - 1) * MULT_KILL
    if not win:
        total += 3

    if fb_victim:  total += 1
    if fb_kill:    total -= 1
    if top_damage: total -= 1

    final = max(MIN_POMPES, floor(total))
    win_str = "Victoire" if win else "Défaite (+3)"
    log.debug(f"{player_name} [{cat_label}] ({win_str}): {final} pompes")
    return int(final), cat_label

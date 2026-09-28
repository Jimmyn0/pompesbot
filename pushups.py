"""
Calcul du nombre de pompes par joueur après une partie.
"""

import logging
from math import floor

from config import (
    DEATHLESS_BONUS,
    DEFAULT_CATEGORY,
    LOSS_STREAK_MULTIPLIER,
    LOSS_STREAK_THRESHOLD,
    PLAYER_CATEGORIES,
)

log = logging.getLogger("PompesBot")

BETA = 0.5   # poids des assists dans le score offensif


def get_player_category(player_name: str) -> tuple[str, dict]:
    for label, cfg in PLAYER_CATEGORIES.items():
        if label != DEFAULT_CATEGORY and player_name in cfg.get("players", []):
            return label, cfg
    return DEFAULT_CATEGORY, PLAYER_CATEGORIES[DEFAULT_CATEGORY]


def calculate_pushups(
    kills:       int,
    deaths:      int,
    assists:     int,
    player_name: str,
    stats:       dict,
    win:         bool,
    fb_kill:     bool = False,
    fb_victim:   bool = False,
    top_damage:  bool = False,
    loss_streak: int  = 0,
) -> tuple[int, str, dict]:
    """Retourne (nb_pompes, categorie_label, détail du calcul).

    `stats` = KDA moyen {Kbar, Abar, Dbar} ; `loss_streak` = nombre de défaites d'affilée
    dans la session, partie en cours comprise. Le détail est affiché par les boutons de l'embed.
    """
    cat_label, cfg = get_player_category(player_name)
    BASE       = cfg["base"]
    MIN_POMPES = cfg["min_pompes"]
    MULT_MORT  = cfg["mult_mort"]
    MULT_KILL  = cfg["mult_kill"]

    Kbar, Abar, Dbar = stats["Kbar"], stats["Abar"], max(stats["Dbar"], 1)

    score_reel  = kills  + BETA * assists
    score_moyen = max(Kbar + BETA * Abar, 1)
    ratio_off   = score_reel / score_moyen
    ratio_mort  = deaths / Dbar

    death_term = (ratio_mort - 1) * MULT_MORT
    kill_term  = -(ratio_off - 1) * MULT_KILL
    steps: list[tuple[str, float]] = [
        ("Base", BASE),
        ("Morts", death_term),
        ("Kills et assists", kill_term),
    ]
    if not win:    steps.append(("Défaite", 3))
    if fb_victim:  steps.append(("First death", 1))
    if fb_kill:    steps.append(("First blood", -1))
    if top_damage: steps.append(("Top dégâts", -1))

    raw   = sum(v for _, v in steps)
    final = max(MIN_POMPES, floor(raw))
    floored = final > floor(raw)

    streak_applied = not win and loss_streak >= LOSS_STREAK_THRESHOLD
    if streak_applied:
        final = round(final * LOSS_STREAK_MULTIPLIER)

    deathless = deaths == 0
    if deathless:
        final = max(0, final - DEATHLESS_BONUS)

    breakdown = {
        "category":    cat_label,
        "min":         MIN_POMPES,
        "mult_mort":   MULT_MORT,
        "mult_kill":   MULT_KILL,
        "avg":         {"K": round(Kbar, 1), "A": round(Abar, 1), "D": round(Dbar, 1)},
        "kda":         [kills, deaths, assists],
        "ratio_mort":  round(ratio_mort, 2),
        "ratio_off":   round(ratio_off, 2),
        "score_reel":  score_reel,
        "score_moyen": round(score_moyen, 1),
        "steps":       [[label, round(v, 1)] for label, v in steps],
        "raw":         round(raw, 1),
        "floored":     floored,
        "loss_streak": loss_streak if streak_applied else 0,
        "deathless":   deathless,
        "final":       int(final),
    }
    log.debug(f"{player_name} [{cat_label}] : {final} pompes")
    return int(final), cat_label, breakdown

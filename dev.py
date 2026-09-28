"""
Mode test : /test_partie génère une fausse fin de partie (toi + tes potes) et la fait passer
par le même traitement qu'une vraie (embed, boutons, séries, succès, records).

Actif uniquement avec POMPESBOT_DEV=1 et un POMPESBOT_DATA_DIR autre que le dossier du bot
(cf. config.DEV_MODE) : les fausses parties ne touchent jamais les vraies données.
"""

import logging
import random
import time

import discord
from discord import app_commands
from discord.ext import commands

from config import OWNER
from db import known_friends
from loop import post_match
from riot_api import get_puuid

log = logging.getLogger("PompesBot")

# (championId, championName) : de vrais champions, pour que les icônes s'affichent.
CHAMPIONS = [
    (43, "Karma"), (10, "Kayle"), (17, "Teemo"), (7, "Leblanc"), (38, "Kassadin"), (238, "Zed"),
    (99, "Lux"), (51, "Caitlyn"), (22, "Ashe"), (1, "Annie"), (86, "Garen"), (62, "MonkeyKing"),
    (157, "Yasuo"), (25, "Morgana"), (53, "Blitzcrank"), (412, "Thresh"), (222, "Jinx"), (84, "Akali"),
]

# mode -> (queueId, gameMode, fourchettes (kills, morts, assists))
MODES = {
    "ARAM":        (450,  "ARAM",   ((3, 25), (3, 15), (5, 35))),
    "ARAM Mayhem": (2400, "KIWI",   ((5, 30), (4, 16), (8, 40))),
    "URF":         (900,  "URF",    ((5, 30), (3, 12), (5, 25))),
    "Arena":       (1750, "CHERRY", ((2, 12), (2, 9),  (1, 10))),
}


def fake_match(
    players: list[tuple[str, str]],
    mode: str,
    win: bool,
    owner_deathless: bool = False,
    owner_pentakill: bool = False,
    rng: random.Random | None = None,
) -> tuple[str, dict, tuple[int, int]]:
    """Fausse partie : (match_id, info au format match-v5, (tueur, victime) du first blood).

    `players` : [(puuid, pseudo)], le propriétaire en premier. En ARAM/URF ils sont tous dans
    l'équipe 100 ; en Arena, le propriétaire et le premier pote forment un duo, les autres
    potes sont dans d'autres duos.
    """
    rng = rng or random.Random()
    queue, game_mode, (kr, dr, ar) = MODES[mode]
    champions = rng.sample(CHAMPIONS, k=len(CHAMPIONS))
    arena = mode == "Arena"

    slots: list[tuple[str, str, int, int | None]] = []   # (puuid, pseudo, équipe, duo)
    if arena:
        for i, (puuid, name) in enumerate(players):
            slots.append((puuid, name, 0, 1 if i < 2 else i))
        for duo in range(1, max(8, len(players)) + 1):   # 8 duos, complétés par des inconnus
            while sum(1 for s in slots if s[3] == duo) < 2:
                slots.append((f"test-inconnu-{len(slots)}", f"Inconnu {len(slots)}", 0, duo))
    else:
        for puuid, name in players[:5]:
            slots.append((puuid, name, 100, None))
        while len(slots) < 5:
            slots.append((f"test-inconnu-{len(slots)}", f"Inconnu {len(slots)}", 100, None))
        for i in range(5):
            slots.append((f"test-adversaire-{i}", f"Adversaire {i + 1}", 200, None))

    participants = []
    for pid, (puuid, name, team, duo) in enumerate(slots, start=1):
        champ_id, champ_name = champions[(pid - 1) % len(champions)]
        if arena:
            won = win if duo == 1 else rng.random() < 0.4
        else:
            won = win if team == 100 else not win
        k, d, a = rng.randint(*kr), rng.randint(*dr), rng.randint(*ar)
        penta = 0
        if pid == 1 and owner_deathless:
            d = 0
        if pid == 1 and owner_pentakill:
            k, penta = max(k, 12), 1
        participants.append({
            "participantId": pid, "puuid": puuid, "riotIdGameName": name, "teamId": team,
            "playerSubteamId": duo, "championId": champ_id, "championName": champ_name,
            "kills": k, "deaths": d, "assists": a, "win": won, "pentaKills": penta,
            "totalDamageDealtToChampions": rng.randint(5, 70) * 1000 + rng.randint(0, 999),
        })

    killer, victim = rng.sample(range(1, len(participants) + 1), 2)
    if owner_deathless and victim == 1:
        killer, victim = victim, killer
    match_id = f"TEST_{int(time.time() * 1000)}"
    info = {"queueId": queue, "gameMode": game_mode, "gameEndTimestamp": int(time.time() * 1000),
            "participants": participants}
    return match_id, info, (killer, victim)


def setup(bot: commands.Bot) -> None:
    @bot.tree.command(name="test_partie", description="[Mode test] Génère une fausse fin de partie avec toi et tes potes")
    @app_commands.describe(
        mode="Mode de jeu",
        resultat="Victoire, défaite ou au hasard",
        sans_mort="Tu finis la partie sans mourir",
        pentakill="Tu fais un pentakill",
        potes="Nombre de potes dans la partie",
    )
    @app_commands.choices(
        mode=[app_commands.Choice(name=m, value=m) for m in MODES],
        resultat=[
            app_commands.Choice(name="Au hasard", value="hasard"),
            app_commands.Choice(name="Victoire", value="victoire"),
            app_commands.Choice(name="Défaite", value="defaite"),
        ],
    )
    async def cmd_test_partie(
        interaction: discord.Interaction,
        mode: str = "ARAM",
        resultat: str = "hasard",
        sans_mort: bool = False,
        pentakill: bool = False,
        potes: app_commands.Range[int, 0, 4] = 4,
    ) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        owner_puuid = await get_puuid(OWNER["name"], OWNER["tag"])
        if not owner_puuid:
            await interaction.followup.send("Compte propriétaire introuvable chez Riot.", ephemeral=True)
            return

        friends = sorted(known_friends().items(), key=lambda f: -f[1][1])[:potes]
        players = [(owner_puuid, OWNER["name"])] + [(puuid, name) for puuid, (name, _) in friends]
        win = {"victoire": True, "defaite": False}.get(resultat, random.random() < 0.5)
        match_id, info, first_blood = fake_match(players, mode, win, sans_mort, pentakill)

        try:
            await post_match(interaction.channel, match_id, info, mode, time.time(), owner_puuid, first_blood)
        except Exception:
            log.exception("Partie de test : erreur")
            await interaction.followup.send("❌ Erreur pendant la génération (voir les logs).", ephemeral=True)
            return
        await interaction.followup.send(
            f"🧪 Partie de test générée : {mode}, {'victoire' if win else 'défaite'}, "
            f"{len(players)} joueur(s) suivi(s).",
            ephemeral=True,
        )

# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Lancement

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
python main.py
```

Variables d'environnement requises dans `.env` :
```
DISCORD_TOKEN=...
RIOT_API_KEY=...
DISCORD_CHANNEL_ID=...
```

Fichier joueurs (non versionné) :
```bash
cp players.example.json players.json
# puis éditez players.json avec vos pseudos et tags Riot
```

## Architecture

Le bot est découpé en modules spécialisés — `main.py` est le seul point d'entrée, il instancie le bot, enregistre les commandes et démarre la boucle périodique.

**Flux principal (toutes les 30 secondes) :**
`loop.py` → `riot_api.py` (détection nouveau match) → `pushups.py` (calcul pompes) → `embed_builder.py` (formatage Discord)

| Module | Rôle |
|---|---|
| `config.py` | Constantes, liste de joueurs, catégories avec leurs multiplicateurs |
| `riot_api.py` | Couche Riot API : PUUID, historique de matchs, KDA moyen, timeline (first blood) |
| `cache.py` | Persistance JSON sur disque : cache KDA avec TTL 6h (`stats_cache.json`) + totaux de session (`session_totals.json`) |
| `pushups.py` | Formule de calcul des pompes basée sur le ratio KDA réel / KDA moyen des 50 dernières parties |
| `embed_builder.py` | Construction de l'embed Discord post-partie (scoreboard style) |
| `commands.py` | Commandes Discord : `!session`, `!reset_session` (admin), `!refresh_kda` (admin) |

## Catégories de joueurs

Trois catégories dans `players.json` avec des multiplicateurs différents pour les morts/kills :
- `ELT` — base 30 pompes, multiplicateurs élevés
- `CNF` — base 23 pompes
- `STD` (tous les autres) — base 15 pompes

Pour ajouter un joueur : l'ajouter dans `PLAYERS_TO_TRACK` (nom + tag Riot) et optionnellement dans une catégorie de `PLAYER_CATEGORIES` dans `players.json`.

## Formule des pompes

```
total = BASE + (ratio_mort - 1) × MULT_MORT - (ratio_off - 1) × MULT_KILL
```
- `ratio_mort = deaths / Dbar` (Dbar = moyenne des morts sur 50 parties ARAM)
- `ratio_off = (kills + 0.5×assists) / max(Kbar + 0.5×Abar, 1)`
- Défaite : +3 pompes
- First blood victim : +1 / First blood kill : -1 / Top damage : -1
- Résultat planché à `min_pompes` de la catégorie

## Queues surveillées

`TARGET_QUEUE_IDS = [450, 900, 1700]` → ARAM, URF, Arena. Modifier cette liste dans `config.py` pour ajouter/retirer des modes.

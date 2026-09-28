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
# puis renseignez OWNER (votre Riot ID : name + tag)
```

## Architecture

Le bot est découpé en modules spécialisés — `main.py` est le seul point d'entrée, il instancie le bot, enregistre les commandes et démarre la boucle périodique.

**Flux principal (toutes les 30 secondes) :**
`loop.py` → `riot_api.py` (détection nouveau match) → `pushups.py` (calcul pompes) → `embed_builder.py` (formatage Discord)

| Module | Rôle |
|---|---|
| `config.py` | Constantes, liste de joueurs, catégories avec leurs multiplicateurs |
| `riot_api.py` | Client Riot async (aiohttp) avec rate limiter et retries : PUUID, historique de matchs, KDA moyen par queue, timeline (first blood) |
| `cache.py` | Persistance JSON atomique : cache KDA par joueur et par queue, TTL 6h (`stats_cache.json`), totaux de session (`session_totals.json`), parties déjà traitées (`match_state.json`) |
| `pushups.py` | Formule de calcul des pompes basée sur le ratio KDA réel / KDA moyen des 20 dernières parties |
| `embed_builder.py` | Construction de l'embed Discord post-partie : 3 champs inline (Joueur / KDA · Dmg / Pompes), alignés par Discord |
| `champion_icons.py` | Icônes de champion : téléchargées depuis Data Dragon et enregistrées comme emojis d'application à la première apparition (repli : nom du champion) |
| `commands.py` | Commandes Discord : `!session`, `!potes`, `!reset_session` (admin), `!refresh_kda` (admin) |

## Catégories de joueurs

Trois catégories dans `players.json` avec des multiplicateurs différents pour les morts/kills :
- `ELT` — base 30 pompes, multiplicateurs élevés
- `CNF` — base 23 pompes
- `STD` (tous les autres) — base 15 pompes

Les catégories référencent les joueurs par pseudo (`riotIdGameName`, sans le tag).

## Joueurs suivis

Seul le compte `OWNER` de `players.json` est interrogé. Ses potes sont détectés automatiquement : tout coéquipier vu au moins `FRIEND_MIN_GAMES` (2) fois sur ses `FRIEND_LOOKBACK` (40) dernières parties. En Arena, seul le duo du propriétaire compte pour la détection (on y recroise souvent des inconnus dans le lobby), mais un pote déjà connu est compté pour les pompes même s'il est dans un autre duo. Les équipes récentes sont stockées dans `match_state.json` (`recent_teams`). Les parties jouées par les potes sans le propriétaire ne sont pas suivies.

## Formule des pompes

```
total = BASE + (ratio_mort - 1) × MULT_MORT - (ratio_off - 1) × MULT_KILL
```
- `ratio_mort = deaths / Dbar` (Dbar = moyenne des morts sur les 20 dernières parties du même mode)
- `ratio_off = (kills + 0.5×assists) / max(Kbar + 0.5×Abar, 1)`
- Défaite : +3 pompes
- First blood victim : +1 / First blood kill : -1 / Top damage : -1
- Résultat planché à `min_pompes` de la catégorie

## Queues surveillées

`QUEUE_NAMES` dans `config.py` (450 ARAM, 900 URF) définit les modes suivis. L'Arena est reconnue par `gameMode == "CHERRY"` car son queueId change selon les saisons (1700, 1710, 1740, 1750…). Pour un nouveau mode, ajouter aussi un KDA de repli dans `DEFAULT_KDA`.

## Fiabilité

- Tous les appels Riot passent par `riot_api.client` (async, jamais bloquant) : rate limit 20/1s + 100/2min, retry sur 429/5xx/erreur réseau (pas sur les autres 4xx).
- La boucle ne laisse remonter aucune exception. Une partie en échec est réessayée jusqu'à 5 fois.
- `match_state.json` mémorise les parties traitées : au redémarrage, les parties jouées pendant l'arrêt (moins de 12 h) sont postées.
- Les totaux de session ne sont enregistrés qu'après l'envoi de l'embed.

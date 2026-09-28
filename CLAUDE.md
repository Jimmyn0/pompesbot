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

## Tests et lint

```bash
pip install -r requirements-dev.txt
pytest
ruff check .
```

- Les tests sont hors ligne : `tests/conftest.py` crée un `players.json` de test dans un dossier temporaire (via `POMPESBOT_DATA_DIR`) avant d'importer le bot, et chaque test a sa propre base SQLite (fixture `fresh_db`). Les doublures (fausse API Riot, faux salon, fausses interactions) sont dans `tests/fakes.py`.
- `ruff` : pas de `ruff format`, le code aligne volontairement ses colonnes (voir `pyproject.toml`).
- CI : `.github/workflows/ci.yml` (lint + tests sur Python 3.13 et 3.14, build de l'image Docker).

## Mode test

`test-bot.ps1` copie les données dans `data/test` (sauvegarde SQLite), puis lance le bot avec `POMPESBOT_DEV=1`, `POMPESBOT_DATA_DIR=data/test` et le salon `DEV_CHANNEL_ID` du `.env`. `config.DEV_MODE` n'est vrai que si les données ne sont pas dans le dossier du bot. En mode test, `dev.py` ajoute `/test_partie`, qui génère une partie (`dev.fake_match`, IDs `TEST_…`) et la passe à `loop.post_match`, le même traitement que les vraies parties (sans toucher à la détection des potes).

## Données et Docker

`POMPESBOT_DATA_DIR` (par défaut le dossier du bot) contient `players.json` et `pompesbot.db`. L'image Docker utilise `/data` (volume `./data` dans `docker-compose.yml`).

## Architecture

Le bot est découpé en modules spécialisés — `main.py` est le seul point d'entrée, il instancie le bot, enregistre les commandes et démarre la boucle périodique.

**Flux principal (toutes les 30 secondes) :**
`loop.py` → `riot_api.py` (détection nouveau match) → `pushups.py` (calcul pompes) → `embed_builder.py` (formatage Discord)

| Module | Rôle |
|---|---|
| `config.py` | Constantes, liste de joueurs, catégories avec leurs multiplicateurs |
| `riot_api.py` | Client Riot async (aiohttp) avec rate limiter et retries : PUUID, historique de matchs, KDA moyen par queue, timeline (first blood) |
| `db.py` | Persistance SQLite (`pompesbot.db`, stdlib `sqlite3`) : cache KDA par PUUID et par queue (TTL 6h), historique des parties (`games`), sessions, parties traitées, équipes récentes du propriétaire. Importe les anciens JSON au premier lancement (renommés en `*.migrated`) |
| `pushups.py` | Formule de calcul des pompes basée sur le ratio KDA réel / KDA moyen des 20 dernières parties |
| `embed_builder.py` | Construction de l'embed Discord post-partie : 3 champs inline (Joueur / KDA · Dmg / Pompes), alignés par Discord ; `mark_player_done` ajoute ✅ sur la ligne d'un joueur |
| `views.py` | Boutons sous l'embed (DynamicItem, fonctionnels après redémarrage) : un par joueur avec l'icône de son champion (`pompes:detail:<match_id>:<participantId>`, détail du calcul en message éphémère) et « ✅ J'ai fait mes pompes » (`pompes:done:<match_id>`) |
| `achievements.py` | Succès (une fois par joueur, table `achievements`) et records de la saison (année civile) |
| `reports.py` | Embeds de bilan : fin de session, récap hebdo, `/stats`, `/succes`, détail du calcul des pompes |
| `lcu.py` | Lecture de l'historique du client League du PC (API locale, lockfile) pour les parties que Riot n'expose pas (ARAM Mayhem) ; conversion au format match-v5 |
| `dev.py` | Mode test : `/test_partie` et génération de fausses parties |
| `champion_icons.py` | Icônes de champion : téléchargées depuis Data Dragon et enregistrées comme emojis d'application à la première apparition (repli : nom du champion) |
| `commands.py` | Slash commands : `/session`, `/stats`, `/succes`, `/lier`, `/potes`, `/reset_session` (admin), `/refresh_kda` (admin), avec autocomplétion des pseudos. Synchronisées au démarrage sur le serveur du salon `DISCORD_CHANNEL_ID` |

## Catégories de joueurs

Trois catégories dans `players.json` avec des multiplicateurs différents pour les morts/kills :
- `ELT` — base 30 pompes, multiplicateurs élevés
- `CNF` — base 23 pompes
- `STD` (tous les autres) — base 15 pompes

Les catégories référencent les joueurs par pseudo (`riotIdGameName`, sans le tag).

## Joueurs suivis

Seul le compte `OWNER` de `players.json` est interrogé. Ses potes sont détectés automatiquement : tout coéquipier vu au moins `FRIEND_MIN_GAMES` (2) fois sur ses `FRIEND_LOOKBACK` (40) dernières parties. En Arena, seul le duo du propriétaire compte pour la détection (on y recroise souvent des inconnus dans le lobby), mais un pote déjà connu est compté pour les pompes même s'il est dans un autre duo. Les équipes récentes sont stockées dans la table `owner_teams`. Les parties jouées par les potes sans le propriétaire ne sont pas suivies.

## Formule des pompes

```
total = BASE + (ratio_mort - 1) × MULT_MORT - (ratio_off - 1) × MULT_KILL
```
- `ratio_mort = deaths / Dbar` (Dbar = moyenne des morts sur les 20 dernières parties du même mode)
- `ratio_off = (kills + 0.5×assists) / max(Kbar + 0.5×Abar, 1)`
- Défaite : +3 pompes
- First blood victim : +1 / First blood kill : -1 / Top damage : -1
- Résultat planché à `min_pompes` de la catégorie
- Série noire : à partir de la 3e défaite d'affilée dans la session, ×1,2 (`LOSS_STREAK_*`)
- Intouchable (0 mort) : −5 après le plancher, sans descendre sous 0 (`DEATHLESS_BONUS`)
- `calculate_pushups` renvoie aussi le détail du calcul, stocké en JSON dans `games.breakdown` et affiché par les boutons de détail

## Queues surveillées

`QUEUE_NAMES` dans `config.py` (450 ARAM, 2400 ARAM Mayhem, 900 et 1900 URF) définit les modes suivis. L'Arena est reconnue par `gameMode == "CHERRY"` car son queueId change selon les saisons (1700, 1710, 1740, 1750…). Pour un nouveau mode, ajouter aussi un KDA de repli dans `DEFAULT_KDA`.

## ARAM Mayhem (ARAM du chaos) et client League

L'API publique de Riot n'expose pas les parties d'ARAM Mayhem (queue 2400) : absentes de l'historique et refusées par ID (403). `lcu.py` les lit dans l'historique du client League ouvert sur le PC du bot (lockfile dans `LCU_LOCKFILES`, `LCU_LOCKFILE` dans le `.env` pour un autre dossier), et `loop._scan_client_games` les fait passer par `post_match` à chaque scan.

- Seules les queues de `LCU_QUEUES` sont lues depuis le client ; les autres restent à l'API Riot.
- Le client utilise des PUUID bruts, l'API Riot des PUUID chiffrés propres à la clé : `loop._client_match_info` retrouve les seconds via le Riot ID de chaque joueur, et le compte connecté est reconnu par Riot ID (`_is_owner`).
- Première lecture du client (`meta.lcu_seeded`) : l'historique sert à détecter les potes, rien n'est posté.
- KDA de référence : moyenne des parties de ce mode dans l'historique du client (`lcu.kda_baseline`).
- Client fermé, autre compte connecté ou bot hébergé ailleurs : rien n'est lu, sans erreur. Les parties de moins de 12 h sont rattrapées à la réouverture.
- Les tests n'accèdent jamais au vrai client (`LCU_LOCKFILE` pointé vers un fichier absent dans `conftest.py`) ; faux client : `FakeClientLoL`.

## Fiabilité

- Tous les appels Riot passent par `riot_api.client` (async, jamais bloquant) : rate limit 20/1s + 100/2min, retry sur 429/5xx/erreur réseau (pas sur les autres 4xx).
- La boucle ne laisse remonter aucune exception. Une partie en échec est réessayée jusqu'à 5 fois.
- La table `processed_matches` mémorise les parties traitées : au redémarrage, les parties jouées pendant l'arrêt (moins de 12 h) sont postées.
- Les résultats (`games`) ne sont enregistrés qu'après l'envoi de l'embed.

## Sessions

Une session regroupe les parties jusqu'à `SESSION_IDLE_HOURS` (6 h) sans partie : elle est alors clôturée automatiquement et son bilan posté (vérifié à chaque scan, et à chaque partie traitée pour le rattrapage après un arrêt). `/reset_session` la clôt à la main. Rien n'est effacé : l'historique complet reste dans `games`.

## Pompes faites

Chaque joueur lie son compte Discord à son pseudo avec `/lier` (table `discord_links`). Le bouton ✅ sous un embed ne valide que les pompes du joueur lié (`games.done_at`). `/session`, `/stats` et le récap hebdo affichent les pompes faites / dues.

## Succès et records

`achievements.ACHIEVEMENTS` liste les succès. Ceux d'une partie sont évalués en lecture seule (`new_game_achievements`), annoncés dans l'embed, puis enregistrés (`db.unlock`) seulement après l'envoi : un échec Discord suivi d'un nouvel essai les annonce quand même. Centurion et Machine (pompes validées) sont vérifiés au clic sur ✅. Les records de la saison (pompes, kills, dégâts sur une partie) ne sont annoncés qu'à partir de `RECORD_MIN_GAMES` parties dans l'année.

## Récap hebdo

Posté le lundi à 10 h, heure de Paris (`RECAP_WEEKDAY`, `RECAP_HOUR`, `TIMEZONE`), sur les 7 jours précédents. Vérifié toutes les 15 min : s'il n'a pas pu partir à l'heure (bot éteint), il part au démarrage suivant dans la semaine. La semaine du dernier récap est stockée dans `meta` (`last_recap_week`) ; au tout premier lancement, aucun récap rétroactif n'est posté.

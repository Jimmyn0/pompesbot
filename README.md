# PompesBot 🏋️

Bot Discord qui traque les parties ARAM / URF / Arena d'un groupe d'amis sur League of Legends et calcule des **pompes** à faire selon les performances (kills, morts, KDA moyen).

## Fonctionnement

Après chaque partie détectée via l'API Riot, le bot poste un embed dans un salon Discord avec :
- le nombre de pompes calculé pour chaque joueur
- le KDA de la partie vs la moyenne des 20 dernières
- une mise en cache du KDA (TTL 6h) pour limiter les appels API

Tout est stocké dans une base SQLite locale (`pompesbot.db`) : historique des parties, sessions, cache.

Les joueurs sont répartis en catégories (`ELT`, `CNF`, `STD`) avec des multiplicateurs différents.

## Fonctionnalités

- Bouton **✅ J'ai fait mes pompes** sous chaque partie
- Sessions clôturées automatiquement après 6 h sans partie, avec bilan
- Récap hebdo le lundi à 10 h : classement, joueur le plus sage, pire partie, pompes en retard
- Modes suivis : ARAM, ARAM Mayhem, URF, Arena

## Prérequis

- Python 3.13+ (ou Docker)
- Un token Discord bot ([discord.com/developers](https://discord.com/developers))
- Une clé API Riot ([developer.riotgames.com](https://developer.riotgames.com))

## Installation

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Configuration

Créez un fichier `.env` à la racine :

```env
DISCORD_TOKEN=votre_token_discord
RIOT_API_KEY=votre_clé_riot
DISCORD_CHANNEL_ID=id_du_salon
```

## Lancement

```bash
python main.py
```

## Hébergement avec Docker

```bash
mkdir data
cp players.json data/        # et pompesbot.db si vous migrez une installation existante
docker compose up -d --build
```

Le conteneur redémarre automatiquement. `players.json` et la base SQLite sont dans `./data` (volume `/data`), les secrets dans `.env`.

## Joueurs suivis

Renseignez votre Riot ID (`OWNER`) dans `players.json` (non versionné). Vos potes sont détectés automatiquement parmi vos coéquipiers récurrents (au moins 2 parties ensemble sur les 40 dernières), et `/potes` les liste.

## Commandes

| Commande | Rôle |
|---|---|
| `/session` | Classement des pompes de la session en cours (faites / dues) |
| `/stats [joueur]` | Statistiques d'un joueur : pompes, KDA, champion favori et maudit, pire partie |
| `/lier <joueur>` | Associe ton compte Discord à ton pseudo LoL (nécessaire pour le bouton ✅) |
| `/potes` | Potes détectés automatiquement |
| `/reset_session` | Clôt la session (admin, l'historique est conservé) |
| `/refresh_kda` | Force le recalcul du KDA moyen d'un joueur (admin) |

```bash
cp players.example.json players.json
```

## Développement

```bash
pip install -r requirements-dev.txt
pytest          # tests (hors ligne : fausse API Riot, faux Discord, base SQLite temporaire)
ruff check .    # lint
```

La CI GitHub Actions lance le lint et les tests sur Python 3.13 et 3.14, et construit l'image Docker, à chaque PR et à chaque push sur `main`.

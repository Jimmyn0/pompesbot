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
- Un bouton par joueur (icône de son champion) : le détail du calcul de ses pompes, visible seulement par celui qui clique
- Défis : série noire (×1,2 à partir de 3 défaites d'affilée), bonus Intouchable (−5 sans mourir)
- 9 succès à débloquer (`/succes`) et records de la saison annoncés dans l'embed
- Sessions clôturées automatiquement après 6 h sans partie, avec bilan
- Récap hebdo le lundi à 10 h : classement, joueur le plus sage, pire partie, pompes en retard
- Modes suivis : ARAM, ARAM du chaos (Mayhem), URF, Arena

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

## Tester le bot

**Tests automatiques** (quelques secondes, sans Discord ni Riot) : voir « Développement » plus bas.

**Mode test** : le vrai bot, sur une copie des données, avec `/test_partie` pour générer de fausses fins de partie.

1. Ajoutez l'ID du salon de test dans `.env` : `DEV_CHANNEL_ID=...`
2. Lancez :
   ```powershell
   .\test-bot.ps1          # réutilise la copie data\test si elle existe
   .\test-bot.ps1 -Reset   # repart d'une copie fraîche des vraies données
   ```
   Si PowerShell bloque le script : `powershell -ExecutionPolicy Bypass -File .\test-bot.ps1`
3. Dans Discord : `/test_partie mode:Arena resultat:Défaite sans_mort:True`. La partie générée (vous et vos potes) passe par le même traitement qu'une vraie : embed, boutons, séries, succès, records.

Les fausses parties ne touchent jamais les vraies données : `/test_partie` n'existe que si `POMPESBOT_DEV=1` **et** que les données sont ailleurs que dans le dossier du bot.

## Hébergement avec Docker

```bash
mkdir data
cp players.json data/        # et pompesbot.db si vous migrez une installation existante
docker compose up -d --build
```

Le conteneur redémarre automatiquement. `players.json` et la base SQLite sont dans `./data` (volume `/data`), les secrets dans `.env`.

## ARAM du chaos (Mayhem)

Riot n'expose pas ces parties dans son API publique. Le bot les lit dans l'historique du **client League ouvert sur le même PC** : elles ne sont vues que si le bot tourne sur le PC où vous jouez, avec le client ouvert (les parties de moins de 12 h sont rattrapées à sa réouverture). Si le client n'est pas installé dans `C:\` ou `D:\Riot Games\League of Legends`, indiquez son lockfile dans `.env` : `LCU_LOCKFILE=...\League of Legends\lockfile`.

## Joueurs suivis

Renseignez votre Riot ID (`OWNER`) dans `players.json` (non versionné). Vos potes sont détectés automatiquement parmi vos coéquipiers récurrents (au moins 2 parties ensemble sur les 40 dernières), et `/potes` les liste.

## Commandes

| Commande | Rôle |
|---|---|
| `/session` | Classement des pompes de la session en cours (faites / dues) |
| `/stats [joueur]` | Statistiques d'un joueur : pompes, KDA, champion favori et maudit, pire partie |
| `/succes [joueur]` | Succès débloqués et restants |
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

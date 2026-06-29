# PompesBot 🏋️

Bot Discord qui traque les parties ARAM / URF d'un groupe d'amis sur League of Legends et calcule des **pompes** à faire selon les performances (kills, morts, KDA moyen).

## Fonctionnement

Après chaque partie détectée via l'API Riot, le bot poste un embed dans un salon Discord avec :
- le nombre de pompes calculé pour chaque joueur
- le KDA de la partie vs la moyenne des 50 dernières
- une mise en cache JSON du KDA (TTL 6h) pour limiter les appels API

Les joueurs sont répartis en catégories (`ELT`, `CNF`, `STD`) avec des multiplicateurs différents.

## Prérequis

- Python 3.13+
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
python app2_2.py
```

## Joueurs suivis

Le bot suit 9 joueurs EUW configurés dans `app2_2.py` (`PLAYERS_TO_TRACK`).

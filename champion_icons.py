"""
Icônes de champion affichées dans les embeds.

Les icônes viennent de Data Dragon (CDN statique de Riot) et sont enregistrées comme emojis
de l'application Discord, à la première apparition de chaque champion. Les emojis
d'application sont utilisables sur tous les serveurs, sans permission particulière.
En cas d'échec, le nom du champion est affiché à la place.
"""

import logging

import aiohttp
import discord

log = logging.getLogger("PompesBot")

DDRAGON = "https://ddragon.leagueoflegends.com"

_bot: discord.Client | None = None
_emojis: dict[str, discord.Emoji] = {}
_ddragon_ids: dict[int, str] = {}     # championId -> id Data Dragon (ex. 62 -> "MonkeyKing")
_version: str | None = None


async def setup(bot: discord.Client) -> None:
    global _bot
    _bot = bot
    try:
        _emojis.update({e.name: e for e in await bot.fetch_application_emojis()})
        log.info(f"{len(_emojis)} icône(s) de champion déjà enregistrée(s)")
    except discord.HTTPException as e:
        log.warning(f"Emojis d'application indisponibles : {e}")


async def _fetch(session: aiohttp.ClientSession, url: str) -> bytes:
    async with session.get(url) as resp:
        resp.raise_for_status()
        return await resp.read()


async def _load_ddragon(session: aiohttp.ClientSession) -> None:
    """Associe championId -> id Data Dragon (les championName des matchs ne correspondent pas toujours)."""
    global _version
    async with session.get(f"{DDRAGON}/api/versions.json") as resp:
        _version = (await resp.json())[0]
    async with session.get(f"{DDRAGON}/cdn/{_version}/data/en_US/champion.json") as resp:
        data = (await resp.json())["data"]
    _ddragon_ids.update({int(c["key"]): c["id"] for c in data.values()})


async def champion_name(champion_id: int) -> str:
    """Nom (id Data Dragon, ex. « MonkeyKing ») d'un champion à partir de son numéro.

    Le client League ne donne que le numéro ; les matchs Riot donnent aussi le nom.
    """
    if champion_id not in _ddragon_ids:
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
                await _load_ddragon(session)
        except Exception as e:
            log.warning(f"Data Dragon indisponible : {e!r}")
    return _ddragon_ids.get(champion_id, f"Champion {champion_id}")


async def champion_icon(champion_id: int, champion_name: str) -> str:
    """Emoji du champion (ex. <:Karma:123…>), ou son nom si l'icône est indisponible."""
    if _bot is None:
        return champion_name
    known = _ddragon_ids.get(champion_id)
    if known in _emojis:
        return str(_emojis[known])
    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            if champion_id not in _ddragon_ids:
                await _load_ddragon(session)
            ddragon_id = _ddragon_ids.get(champion_id)
            if not ddragon_id:
                return champion_name
            if ddragon_id in _emojis:
                return str(_emojis[ddragon_id])

            image = await _fetch(session, f"{DDRAGON}/cdn/{_version}/img/champion/{ddragon_id}.png")
        emoji = await _bot.create_application_emoji(name=ddragon_id, image=image)
        _emojis[ddragon_id] = emoji
        log.info(f"Icône ajoutée pour {ddragon_id}")
        return str(emoji)
    except Exception as e:
        log.warning(f"Icône indisponible pour {champion_name} : {e!r}")
        return champion_name

"""
Doublures de test : API Riot, salon et interactions Discord.
"""

import discord


def participant(pid, puuid, team, k=0, d=0, a=0, dmg=0, win=True, sub=None, champion="Jinx"):
    """Participant d'un match-v5 ; le pseudo est le PUUID sans son « p » initial (pA -> A)."""
    return {
        "participantId": pid, "puuid": puuid, "riotIdGameName": puuid[1:], "teamId": team,
        "playerSubteamId": sub, "kills": k, "deaths": d, "assists": a,
        "totalDamageDealtToChampions": dmg, "win": win, "championName": champion, "championId": 0,
    }


def match(queue, participants, ended_ms=None, game_mode=None):
    info = {"queueId": queue, "participants": participants}
    if ended_ms is not None:
        info["gameEndTimestamp"] = ended_ms
    if game_mode:
        info["gameMode"] = game_mode
    return {"info": info}


class FakeRiot:
    """Historique du propriétaire (pA) et détails de match, modifiables par les tests."""

    def __init__(self):
        self.history: list[str] = []      # du plus ancien au plus récent
        self.matches: dict[str, dict] = {}
        self.first_blood = (1, 2)
        self.kda = {"Kbar": 5, "Abar": 10, "Dbar": 5}
        self.kda_calls: list[str] = []

    def add(self, match_id, m):
        self.history.append(match_id)
        self.matches[match_id] = m

    async def get_puuid(self, name, tag):
        return "p" + name

    async def get_recent_match_ids(self, puuid, count=5, queue=None):
        return list(reversed(self.history))[:count]

    async def get_match_detail(self, match_id):
        return self.matches.get(match_id)

    async def get_first_blood(self, match_id):
        return self.first_blood

    async def get_player_kda_stats(self, name, puuid, queue, mode="ARAM"):
        self.kda_calls.append(name)
        return dict(self.kda)


class FakeChannel:
    def __init__(self, fail_times=0):
        self.sent: list[tuple] = []
        self.fail_times = fail_times

    async def send(self, content=None, embed=None, view=None, **kwargs):
        if self.fail_times:
            self.fail_times -= 1
            raise discord.HTTPException(_FakeResponse(), "discord indisponible")
        self.sent.append((embed, view))

    @property
    def embeds(self):
        return [e for e, _ in self.sent]


class _FakeResponse:
    status = 503
    reason = "Service Unavailable"


class FakeBot:
    def __init__(self, channel):
        self.channel = channel

    def get_channel(self, channel_id):
        return self.channel


class _Response:
    def __init__(self):
        self.messages: list[tuple] = []   # (content, embed, ephemeral)
        self.edited = None

    async def send_message(self, content=None, embed=None, ephemeral=False):
        self.messages.append((content, embed, ephemeral))

    async def edit_message(self, embed=None, **kwargs):
        self.edited = embed


class _Followup:
    def __init__(self):
        self.messages: list[str] = []

    async def send(self, content=None, ephemeral=False):
        self.messages.append(content)


class _User:
    def __init__(self, user_id):
        self.id = user_id
        self.mention = f"<@{user_id}>"


class _Message:
    def __init__(self, embed):
        self.embeds = [embed] if embed else []


class FakeInteraction:
    def __init__(self, user_id=1, embed=None):
        self.user = _User(user_id)
        self.response = _Response()
        self.followup = _Followup()
        self.message = _Message(embed)

    @property
    def reply(self):
        """(content, embed, ephemeral) de la première réponse."""
        return self.response.messages[0]

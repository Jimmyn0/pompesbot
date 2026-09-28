import time

import pytest
from aiohttp import web

import riot_api


@pytest.fixture
async def server(monkeypatch):
    """Faux serveur Riot local ; le client est redirigé dessus et ne fait pas de pause."""
    calls: dict[str, int] = {}
    responses: dict[str, list] = {}   # chemin -> [fabrique de réponse, ...] ; la dernière est répétée

    async def handler(request):
        path = request.path
        calls[path] = calls.get(path, 0) + 1
        queue = responses.get(path) or [lambda: web.Response(status=404)]
        return (queue.pop(0) if len(queue) > 1 else queue[0])()

    app = web.Application()
    app.router.add_get("/{tail:.*}", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]

    client = riot_api.RiotClient("test")
    client.limiter = riot_api.RateLimiter([(1000, 1.0)])
    await client.start()
    original_get = client.session.get

    def local_get(url, params=None):
        return original_get(url.replace(f"https://{riot_api.REGION_V5}.api.riotgames.com",
                                        f"http://127.0.0.1:{port}"), params=params)

    client.session.get = local_get
    monkeypatch.setattr(riot_api, "BACKOFF_BASE", 0)

    yield client, responses, calls
    await client.close()
    await runner.cleanup()


async def test_rate_limiter_spaces_requests():
    limiter = riot_api.RateLimiter([(5, 0.5)])
    start = time.monotonic()
    for _ in range(11):
        await limiter.acquire()
    # 11 requêtes à 5 par 0,5 s : deux attentes de 0,5 s.
    assert 0.95 <= time.monotonic() - start < 1.5


async def test_retries_after_429_and_5xx(server):
    client, responses, calls = server
    responses["/a"] = [
        lambda: web.Response(status=429, headers={"Retry-After": "0"}),
        lambda: web.Response(status=503),
        lambda: web.json_response({"puuid": "X"}),
    ]
    assert await client.get("/a") == {"puuid": "X"}
    assert calls["/a"] == 3


async def test_404_returns_none(server):
    client, _, _ = server
    assert await client.get("/absent") is None


async def test_other_4xx_not_retried(server):
    client, responses, calls = server
    responses["/bad"] = [lambda: web.Response(status=400)]
    assert await client.get("/bad") is None
    assert calls["/bad"] == 1


async def test_gives_up_after_max_retries(server):
    client, responses, calls = server
    responses["/down"] = [lambda: web.Response(status=500)]
    assert await client.get("/down") is None
    assert calls["/down"] == riot_api.MAX_RETRIES


async def test_network_error_returns_none(monkeypatch):
    monkeypatch.setattr(riot_api, "BACKOFF_BASE", 0)
    monkeypatch.setattr(riot_api, "MAX_RETRIES", 1)   # un refus de connexion prend ~2 s sous Windows
    client = riot_api.RiotClient("test")
    client.limiter = riot_api.RateLimiter([(1000, 1.0)])
    await client.start()
    original_get = client.session.get
    client.session.get = lambda url, params=None: original_get("http://127.0.0.1:1/x", params=params)
    try:
        assert await client.get("/x") is None
    finally:
        await client.close()


async def test_riot_id_is_url_encoded(monkeypatch):
    seen = []

    async def fake_get(path, params=None):
        seen.append(path)
        return {"puuid": "P"}

    monkeypatch.setattr(riot_api.client, "get", fake_get)
    riot_api.puuid_cache.clear()
    assert await riot_api.get_puuid("Bard est là", "EUW") == "P"
    assert seen == ["/riot/account/v1/accounts/by-riot-id/Bard%20est%20l%C3%A0/EUW"]


async def test_no_riot_call_for_client_only_modes(monkeypatch):
    calls = []

    async def fake_get(path, params=None):
        calls.append(path)
        return []

    monkeypatch.setattr(riot_api.client, "get", fake_get)
    stats = await riot_api.get_player_kda_stats("A", "pA", 2400, "ARAM Mayhem")
    assert stats == riot_api.DEFAULT_KDA["ARAM Mayhem"] and calls == []

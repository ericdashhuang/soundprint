import asyncio

import respx
from httpx import ConnectError, Response

from app.config import get_settings
from app.warmup import warm_up_external_clients

TOKEN_RESPONSE = {"access_token": "warmup-token", "token_type": "Bearer", "expires_in": 3600}


@respx.mock
def test_warm_up_calls_spotify_token_search_and_reccobeats():
    token_route = respx.post("https://accounts.spotify.com/api/token").mock(
        return_value=Response(200, json=TOKEN_RESPONSE)
    )
    search_route = respx.get(url__regex=r"https://api\.spotify\.com/v1/search\?.*").mock(
        return_value=Response(200, json={"artists": {"items": []}})
    )
    reccobeats_route = respx.get(url__regex=r"https://api\.reccobeats\.com/v1/track\?.*").mock(
        return_value=Response(200, json={"content": []})
    )

    asyncio.run(warm_up_external_clients(get_settings()))

    assert token_route.call_count == 1
    assert search_route.call_count == 1
    assert reccobeats_route.call_count == 1


@respx.mock
def test_warm_up_never_raises_when_spotify_is_unreachable():
    respx.post("https://accounts.spotify.com/api/token").mock(side_effect=ConnectError("down"))
    reccobeats_route = respx.get(url__regex=r"https://api\.reccobeats\.com/v1/track\?.*").mock(
        return_value=Response(200, json={"content": []})
    )

    # Should not raise even though the Spotify leg fails outright - a failed
    # warm-up must never block server startup.
    asyncio.run(warm_up_external_clients(get_settings()))

    assert reccobeats_route.call_count == 1

import asyncio

import respx
from httpx import Response

from app.config import get_settings
from app.spotify_client import SpotifyClient, SpotifyRateLimitedError

ARTIST_ID = "4Z8W4fKeB5YxbusRsdQVPb"


def _mock_token():
    respx.post("https://accounts.spotify.com/api/token").mock(
        return_value=Response(200, json={"access_token": "test-token", "expires_in": 3600})
    )


@respx.mock
def test_retries_after_429_and_respects_retry_after_delay(monkeypatch):
    """a 429 followed by a 200 on retry should succeed rather than raising,
    and should sleep for the delay retry after actually specifies"""
    _mock_token()
    route = respx.get(f"https://api.spotify.com/v1/artists/{ARTIST_ID}")
    route.side_effect = [
        Response(429, headers={"Retry-After": "1"}),
        Response(200, json={"id": ARTIST_ID, "name": "Radiohead"}),
    ]

    sleep_calls = []

    async def fake_sleep(seconds):
        sleep_calls.append(seconds)

    monkeypatch.setattr("app.spotify_client.asyncio.sleep", fake_sleep)

    async def run():
        client = SpotifyClient(get_settings())
        try:
            return await client.get_artist(ARTIST_ID)
        finally:
            await client.aclose()

    result = asyncio.run(run())

    assert result == {"id": ARTIST_ID, "name": "Radiohead"}
    assert route.call_count == 2
    assert sleep_calls == [1]


@respx.mock
def test_gives_up_after_max_retries(monkeypatch):
    """a request that keeps returning 429 should eventually raise, not retry forever"""
    _mock_token()
    route = respx.get(f"https://api.spotify.com/v1/artists/{ARTIST_ID}")
    route.mock(return_value=Response(429, headers={"Retry-After": "1"}))

    real_sleep = asyncio.sleep
    monkeypatch.setattr("app.spotify_client.asyncio.sleep", lambda _seconds: real_sleep(0))

    async def run():
        client = SpotifyClient(get_settings())
        try:
            await client.get_artist(ARTIST_ID)
        finally:
            await client.aclose()

    try:
        asyncio.run(run())
        assert False, "expected SpotifyRateLimitedError"
    except SpotifyRateLimitedError:
        pass

    assert route.call_count == 3


@respx.mock
def test_caps_backoff_for_an_extreme_retry_after_value(monkeypatch):
    """a pathologically large retry after (seen live against a request pattern
    spotify treats as abusive) must not sleep for the literal duration, it
    should be capped rather than hanging the request for hours"""
    _mock_token()
    route = respx.get(f"https://api.spotify.com/v1/artists/{ARTIST_ID}")
    route.side_effect = [
        Response(429, headers={"Retry-After": "35466"}),
        Response(200, json={"id": ARTIST_ID, "name": "Radiohead"}),
    ]

    sleep_calls = []

    async def fake_sleep(seconds):
        sleep_calls.append(seconds)

    monkeypatch.setattr("app.spotify_client.asyncio.sleep", fake_sleep)

    async def run():
        client = SpotifyClient(get_settings())
        try:
            return await client.get_artist(ARTIST_ID)
        finally:
            await client.aclose()

    result = asyncio.run(run())

    assert result == {"id": ARTIST_ID, "name": "Radiohead"}
    assert sleep_calls == [10.0]


@respx.mock
def test_concurrent_burst_caps_simultaneous_requests():
    """game_service's tracklist fetch burst must not fire more than
    _MAX_CONCURRENT_ALBUM_TRACK_FETCHES spotify requests at once, this is
    the behavior that trips spotify's real rate limit if left unbounded, so a
    regression here (eg reverting to a plain asyncio.gather with no
    semaphore) must fail this test rather than passing quietly"""
    from app.game_service import (
        _MAX_CONCURRENT_ALBUM_TRACK_FETCHES,
        _filter_out_albums_with_non_studio_tracks,
    )

    _mock_token()
    album_count = _MAX_CONCURRENT_ALBUM_TRACK_FETCHES * 3
    albums = [{"id": f"album-{i}", "name": f"Album {i}"} for i in range(album_count)]

    in_flight = 0
    max_in_flight = 0

    async def handler(request):
        nonlocal in_flight, max_in_flight
        in_flight += 1
        max_in_flight = max(max_in_flight, in_flight)
        await asyncio.sleep(0.01)
        in_flight -= 1
        return Response(200, json={"items": [{"name": "Track One"}]})

    for i in range(album_count):
        respx.get(f"https://api.spotify.com/v1/albums/album-{i}/tracks?limit=50").mock(
            side_effect=handler
        )

    async def run():
        client = SpotifyClient(get_settings())
        try:
            return await _filter_out_albums_with_non_studio_tracks(client, albums)
        finally:
            await client.aclose()

    kept = asyncio.run(run())

    assert len(kept) == album_count
    assert max_in_flight <= _MAX_CONCURRENT_ALBUM_TRACK_FETCHES

"""Eager startup warm-up for this app's outbound third-party connections.

`app/database.py`'s `init_db()` already forces a real Postgres connection at
process startup (`SQLModel.metadata.create_all` has to connect to check/
create tables), so the DB is not lazy. Spotify and ReccoBeats are: nothing
touches either host until a real user request does. On a fresh process (e.g.
right after a Render cold start resolves) that means the *first* artist
autocomplete and the *first* round-start each additionally pay for the first
real DNS+TLS handshake to `accounts.spotify.com`/`api.spotify.com` and to
`api.reccobeats.com`, on top of the request's own work - then every later
request in that same process is fast, because that connection cost was a
one-time, per-process tax rather than something cached per-request (a fresh
`SpotifyClient`, with its own token cache, is created per request - see
app/main.py).

Paying that same one-time tax here, during the FastAPI lifespan startup hook,
moves it before the app starts accepting real traffic instead of onto
whichever user happens to send the first request.
"""

import asyncio
import logging

from app.config import Settings
from app.reccobeats_client import get_track_vibe
from app.spotify_client import SpotifyClient

logger = logging.getLogger(__name__)

# Any short, valid search query works - the response content doesn't matter,
# only that the request round-trips through accounts.spotify.com (token) and
# api.spotify.com (search) once.
_SPOTIFY_WARMUP_QUERY = "a"

# get_track_vibe resolves a track by Spotify ID via ReccoBeats; an ID that
# doesn't exist just yields "no match" (None), which is fine - the point is
# to pay for the connection to api.reccobeats.com, not to get real data.
_RECCOBEATS_WARMUP_TRACK_ID = "0000000000000000000000000000"


async def _warm_up_spotify(settings: Settings) -> None:
    client = SpotifyClient(settings)
    try:
        await client.search_artists(_SPOTIFY_WARMUP_QUERY, limit=1)
    except Exception as exc:  # best-effort warm-up - never blocks startup
        logger.warning("Spotify warm-up request failed: %s", exc)
    finally:
        await client.aclose()


async def _warm_up_reccobeats() -> None:
    # get_track_vibe never raises (see app/reccobeats_client.py) - any failure
    # is already logged there and simply means this warm-up didn't help.
    await get_track_vibe(_RECCOBEATS_WARMUP_TRACK_ID)


async def warm_up_external_clients(settings: Settings) -> None:
    """Best-effort warm-up of every external host this app calls. Never
    raises - a failed warm-up just means the first real request pays the
    cost it would have paid anyway, not that the server fails to start."""
    await asyncio.gather(_warm_up_spotify(settings), _warm_up_reccobeats())

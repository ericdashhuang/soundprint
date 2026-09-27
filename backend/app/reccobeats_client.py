"""primary per track vibe source reccobeats' free audio features api

reccobeats (https://reccobeats.com) republishes spotify audio features shaped
values (energy, valence, danceability, tempo, etc) computed by its own
pipeline, keyed by track identity rather than by needing a 30-second preview
clip to analyze, this is the primary vibe source; app/vibe_analysis.py's
preview+librosa path is now the fallback for whenever reccobeats has no match
(see app/vibe_service.py and the project AGENTS.md for why, preview url
availability turned out to be far rarer in practice than originally assumed)

the contract below was confirmed against reccobeats' own openapi spec (the
json embedded in its docs site's page bundles, not just the rendered html,
which loads request/response details client side and doesn't expose them to
a plain fetch)

  base url https://api.reccobeats.com, no api key or authorization header
    is required for any endpoint used here (confirmed via reccobeats' own
    "introduction" doc page "no api access key or authentication
    required"), there is therefore no RECCOBEATS_API_KEY setting to add
  `GET /v1/track?ids=<id>` resolves one or more tracks by reccobeats id,
    spotify id, *or* isrc, returning each match's own reccobeats uuid, this
    module passes the spotify track id already in hand (from the spotify
    lookup, see app/lookup.py) rather than searching by track name + artist
    via `GET /v1/track/search` an id match is exact, while a name/artist
    text search can silently return the wrong track for a title that exists
    in multiple versions (remaster, live, cover, etc), it also avoids an
    extra spotify call to fetch isrc via `external_ids`, since the spotify
    id is already available and is at least as precise a key
  `GET /v1/track/{reccobeats_id}/audio-features` then returns the actual
    feature vector for that resolved track

field mapping onto this project's VibeOut/TrackVibe shape
  `energy` maps directly, the same 0 to 1 "intensity" concept the librosa
    fallback also produces
  `brightness` has no literal reccobeats analog (the librosa fallback's
    "brightness" is a spectral centroid signal reccobeats doesn't expose)
    reccobeats' `valence` (0 to 1, sad/dark -> happy/bright mood) is used
    instead for this project's bright/cheerful-vs-dark/moody vibe axis it's
    the closer semantic fit of what reccobeats does expose
  `tempo_bpm` maps directly from reccobeats' `tempo`
  `vibe_score` mirrors the librosa fallback's own formula the mean of
    `energy` and `brightness` (here, valence)
  `danceability`, `acousticness`, `instrumentalness`, `speechiness`,
    `loudness`, `key`, and `mode` map directly from reccobeats' own
    identically named fields, confirmed present in the real
    `/audio-features` response, these have no librosa fallback equivalent
    (see app/vibe_analysis.py), so they're only ever set on
    `source == "reccobeats"` rows; a track analyzed via librosa instead
    simply has them as none, they're also read defensively here (missing ->
    none) rather than with direct key access, in case a given reccobeats
    entry doesn't have full coverage for a track

a track reccobeats has no data for (empty `/v1/track` result, or a 404 from
`/audio-features`) is not an error, `get_track_vibe` returns none so the
caller can fall through to the preview+librosa path, any actual connectivity
problem, timeout, rate limit, or malformed response is likewise swallowed and
logged rather than raised, for the same reason
"""

import logging

import httpx

logger = logging.getLogger(__name__)

SOURCE_LABEL = "reccobeats"

BASE_URL = "https://api.reccobeats.com"

# reccobeats has no documented sla on latency, so a request that hangs must
# not stall the whole lookup, a fast, generous enough timeout keeps this
# fallback path from becoming its own outage
_REQUEST_TIMEOUT_SECONDS = 5.0


class ReccoBeatsError(Exception):
    """raised internally for any non-2xx/404 reccobeats response

    never escapes `get_track_vibe`, it's caught there and turned into a
    logged warning plus a none return, exactly like a "no match" result
    """


def _optional_float(data: dict, field: str) -> float | None:
    value = data.get(field)
    return None if value is None else float(value)


def _optional_int(data: dict, field: str) -> int | None:
    value = data.get(field)
    return None if value is None else int(value)


def _vibe_features_from_audio_features(data: dict) -> dict:
    energy = float(data["energy"])
    valence = float(data["valence"])
    tempo = float(data["tempo"])
    vibe_score = round((energy + valence) / 2, 4)
    return {
        "vibe_score": vibe_score,
        "energy": round(energy, 4),
        "brightness": round(valence, 4),
        "tempo_bpm": round(tempo, 2),
        "source": SOURCE_LABEL,
        "danceability": _optional_float(data, "danceability"),
        "acousticness": _optional_float(data, "acousticness"),
        "instrumentalness": _optional_float(data, "instrumentalness"),
        "speechiness": _optional_float(data, "speechiness"),
        "loudness": _optional_float(data, "loudness"),
        "key": _optional_int(data, "key"),
        "mode": _optional_int(data, "mode"),
    }


async def _resolve_reccobeats_id(client: httpx.AsyncClient, spotify_track_id: str) -> str | None:
    response = await client.get(f"{BASE_URL}/v1/track", params={"ids": spotify_track_id})
    if response.status_code != 200:
        raise ReccoBeatsError(f"track lookup failed (status {response.status_code})")

    content = response.json().get("content") or []
    if not content:
        return None
    return content[0]["id"]


async def _fetch_audio_features(client: httpx.AsyncClient, reccobeats_id: str) -> dict | None:
    response = await client.get(f"{BASE_URL}/v1/track/{reccobeats_id}/audio-features")
    if response.status_code == 404:
        return None
    if response.status_code != 200:
        raise ReccoBeatsError(f"audio-features lookup failed (status {response.status_code})")
    return _vibe_features_from_audio_features(response.json())


async def get_track_vibe(
    spotify_track_id: str, http_client: httpx.AsyncClient | None = None
) -> dict | None:
    """look up a track's vibe via reccobeats, keyed by its spotify track id

    returns a dict of vibe_score/energy/brightness/tempo_bpm/source, or none
    when reccobeats has no match or the request fails for any reason, see
    the module docstring and `ReccoBeatsError` for why this never raises
    """
    client = http_client or httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_SECONDS)
    try:
        reccobeats_id = await _resolve_reccobeats_id(client, spotify_track_id)
        if reccobeats_id is None:
            return None
        return await _fetch_audio_features(client, reccobeats_id)
    except (httpx.HTTPError, ReccoBeatsError, KeyError, ValueError, TypeError) as exc:
        logger.warning("ReccoBeats vibe lookup failed for track %s: %s", spotify_track_id, exc)
        return None
    finally:
        if http_client is None:
            await client.aclose()

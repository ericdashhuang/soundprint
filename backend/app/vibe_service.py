"""orchestrates per track vibe analysis with a postgres backed cache

keeps `app/vibe_analysis.py` and `app/reccobeats_client.py` (pure lookup/
analysis, no database) free of database concerns, and keeps this layer free
of spotify concerns, it only needs a track id and an optional preview url

vibe source order cache -> reccobeats (see app/reccobeats_client.py) ->
preview+librosa (see app/vibe_analysis.py) -> none, reccobeats is primary
because it needs no audio at all, and real world spotify preview url
availability has turned out to be far rarer than originally assumed (see the
project AGENTS.md); the preview+librosa path remains as a fallback for
whenever reccobeats has no data for a track
"""

import asyncio
import logging

from sqlmodel import Session

from app.models import TrackVibe
from app.reccobeats_client import get_track_vibe
from app.schemas import VibeOut
from app.vibe_analysis import (
    AudioAnalysisError,
    PreviewDownloadError,
    analyze_audio,
    download_preview_clip,
)

logger = logging.getLogger(__name__)


def _to_vibe_out(row: TrackVibe) -> VibeOut:
    return VibeOut(
        vibe_score=row.vibe_score,
        energy=row.energy,
        brightness=row.brightness,
        tempo_bpm=row.tempo_bpm,
        source=row.source,
        danceability=row.danceability,
        acousticness=row.acousticness,
        instrumentalness=row.instrumentalness,
        speechiness=row.speechiness,
        loudness=row.loudness,
        key=row.key,
        mode=row.mode,
    )


async def _compute_vibe_features(spotify_track_id: str, preview_url: str | None) -> dict | None:
    """pure computation, no db access, so this is safe to run concurrently
    for many tracks at once (see get_or_compute_vibes_bulk)"""
    features = await get_track_vibe(spotify_track_id)

    if features is None and preview_url:
        try:
            clip_bytes = await download_preview_clip(preview_url)
            analyzed = analyze_audio(clip_bytes)
        except (PreviewDownloadError, AudioAnalysisError) as exc:
            logger.warning("Vibe analysis unavailable for track %s: %s", spotify_track_id, exc)
        else:
            features = {
                "vibe_score": analyzed.vibe_score,
                "energy": analyzed.energy,
                "brightness": analyzed.brightness,
                "tempo_bpm": analyzed.tempo_bpm,
                "source": analyzed.source,
            }

    return features


async def get_or_compute_vibe(
    session: Session, spotify_track_id: str, preview_url: str | None
) -> VibeOut | None:
    """return the cached vibe for a track, computing and caching it if needed

    tries reccobeats first (no preview clip needed), then falls back to the
    preview+librosa path if reccobeats has no match and a preview url exists
    returns none (never raises) when none of that is available, a missing
    vibe should never fail the whole lookup request
    """
    cached = session.get(TrackVibe, spotify_track_id)
    if cached is not None:
        return _to_vibe_out(cached)

    features = await _compute_vibe_features(spotify_track_id, preview_url)
    if features is None:
        return None

    row = TrackVibe(spotify_track_id=spotify_track_id, **features)
    session.add(row)
    session.commit()
    return _to_vibe_out(row)


async def get_or_compute_vibes_bulk(
    session: Session, tracks: list[tuple[str, str | None]]
) -> dict[str, VibeOut | None]:
    """same as get_or_compute_vibe, but for a whole album's worth of tracks
    at once

    the cache check and db writes stay sequential (sqlalchemy's synchronous
    `Session` isn't safe for concurrent use), but the slow part, the
    ReccoBeats/librosa network calls for whichever tracks miss the cache -
    runs concurrently via asyncio.gather, this exists specifically because
    the album guessing game's round start was looping get_or_compute_vibe
    one track at a time, which serialized what can be dozens of network
    round trips confirmed live at ~16s for a single 14-track album on a
    cold cache (and the game may try up to 3 candidate albums before
    settling on one with enough vibe data), which is indistinguishable from
    "hung" to an end user, concurrent lookups cut this to roughly the
    slowest single track's round trip
    """
    results: dict[str, VibeOut | None] = {}
    misses: list[tuple[str, str | None]] = []

    for spotify_track_id, preview_url in tracks:
        cached = session.get(TrackVibe, spotify_track_id)
        if cached is not None:
            results[spotify_track_id] = _to_vibe_out(cached)
        else:
            misses.append((spotify_track_id, preview_url))

    if not misses:
        return results

    computed = await asyncio.gather(
        *(_compute_vibe_features(track_id, preview_url) for track_id, preview_url in misses)
    )

    for (spotify_track_id, _preview_url), features in zip(misses, computed):
        if features is None:
            results[spotify_track_id] = None
            continue
        row = TrackVibe(spotify_track_id=spotify_track_id, **features)
        session.add(row)
        results[spotify_track_id] = _to_vibe_out(row)

    session.commit()
    return results

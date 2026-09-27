import asyncio
import time
from unittest.mock import AsyncMock, patch

import pytest
from sqlmodel import Session

from app.database import get_engine
from app.models import TrackVibe
from app.vibe_analysis import AudioAnalysisError, VibeFeatures
from app.vibe_service import get_or_compute_vibe, get_or_compute_vibes_bulk

FAKE_LIBROSA_FEATURES = VibeFeatures(vibe_score=0.5, energy=0.4, brightness=0.6, tempo_bpm=120.0)
FAKE_RECCOBEATS_FEATURES = {
    "vibe_score": 0.65,
    "energy": 0.7,
    "brightness": 0.6,
    "tempo_bpm": 128.0,
    "source": "reccobeats",
}


@pytest.fixture()
def session(client):
    # `client` fixture (from conftest) already calls init_db() against the
    # shared in memory sqlite engine
    with Session(get_engine()) as db_session:
        yield db_session


@patch("app.vibe_service.get_track_vibe", new_callable=AsyncMock, return_value=FAKE_RECCOBEATS_FEATURES)
def test_reccobeats_match_is_used_and_cached(mock_get_track_vibe, session):
    first = asyncio.run(get_or_compute_vibe(session, "track-recco", None))
    second = asyncio.run(get_or_compute_vibe(session, "track-recco", None))

    assert first == second
    assert first.vibe_score == 0.65
    assert first.source == "reccobeats"
    mock_get_track_vibe.assert_awaited_once()


@patch("app.vibe_service.analyze_audio", return_value=FAKE_LIBROSA_FEATURES)
@patch("app.vibe_service.download_preview_clip", new_callable=AsyncMock, return_value=b"fake-mp3")
@patch("app.vibe_service.get_track_vibe", new_callable=AsyncMock, return_value=None)
def test_reccobeats_miss_falls_back_to_librosa(
    mock_get_track_vibe, mock_download, mock_analyze, session
):
    result = asyncio.run(
        get_or_compute_vibe(session, "track-abc", "https://example.com/preview.mp3")
    )

    assert result.vibe_score == 0.5
    assert result.source == "librosa_fallback"
    mock_get_track_vibe.assert_awaited_once()
    mock_download.assert_awaited_once()
    mock_analyze.assert_called_once()


@patch("app.vibe_service.get_track_vibe", new_callable=AsyncMock, return_value=None)
def test_second_lookup_of_same_track_does_not_reanalyze(mock_get_track_vibe, session):
    with patch(
        "app.vibe_service.analyze_audio", return_value=FAKE_LIBROSA_FEATURES
    ) as mock_analyze, patch(
        "app.vibe_service.download_preview_clip",
        new_callable=AsyncMock,
        return_value=b"fake-mp3",
    ) as mock_download:
        first = asyncio.run(
            get_or_compute_vibe(session, "track-second-lookup", "https://example.com/preview.mp3")
        )
        second = asyncio.run(
            get_or_compute_vibe(session, "track-second-lookup", "https://example.com/preview.mp3")
        )

    assert first == second
    assert first.vibe_score == 0.5
    mock_download.assert_awaited_once()
    mock_analyze.assert_called_once()
    assert mock_get_track_vibe.await_count == 1


@patch("app.vibe_service.get_track_vibe", new_callable=AsyncMock, return_value=None)
def test_analysis_failure_returns_none_gracefully(mock_get_track_vibe, session):
    with patch("app.vibe_service.analyze_audio") as mock_analyze, patch(
        "app.vibe_service.download_preview_clip",
        new_callable=AsyncMock,
        return_value=b"junk",
    ) as mock_download:
        mock_analyze.side_effect = AudioAnalysisError("decode failed")

        result = asyncio.run(
            get_or_compute_vibe(session, "track-bad-audio", "https://example.com/bad.mp3")
        )

    assert result is None


@patch("app.vibe_service.analyze_audio")
@patch("app.vibe_service.download_preview_clip", new_callable=AsyncMock)
@patch("app.vibe_service.get_track_vibe", new_callable=AsyncMock, return_value=None)
def test_both_sources_unavailable_returns_none(
    mock_get_track_vibe, mock_download, mock_analyze, session
):
    result = asyncio.run(get_or_compute_vibe(session, "track-no-preview", None))

    assert result is None
    mock_get_track_vibe.assert_awaited_once()
    mock_download.assert_not_awaited()
    mock_analyze.assert_not_called()


def test_bulk_lookup_skips_cached_tracks_and_only_fetches_misses(session):
    session.add(
        TrackVibe(
            spotify_track_id="track-cached",
            vibe_score=0.9,
            energy=0.9,
            brightness=0.9,
            tempo_bpm=100.0,
            source="reccobeats",
        )
    )
    session.commit()

    with patch(
        "app.vibe_service.get_track_vibe",
        new_callable=AsyncMock,
        return_value=FAKE_RECCOBEATS_FEATURES,
    ) as mock_get_track_vibe:
        result = asyncio.run(
            get_or_compute_vibes_bulk(session, [("track-cached", None), ("track-new", None)])
        )

    assert result["track-cached"].vibe_score == 0.9
    assert result["track-new"].vibe_score == FAKE_RECCOBEATS_FEATURES["vibe_score"]
    mock_get_track_vibe.assert_awaited_once_with("track-new")

    # the newly computed track is now cached too
    assert session.get(TrackVibe, "track-new") is not None


def test_bulk_lookup_runs_cache_misses_concurrently(session):
    """regression test the album guessing game's round start was looping
    get_or_compute_vibe one track at a time, serializing what can be dozens
    of reccobeats round trips into a many seconds long request that looked
    hung to an end user (confirmed live ~16s for one 14-track album on a
    cold cache), concurrent lookups should take roughly one round trip's
    worth of time, not n round trips'"""

    async def slow_vibe(spotify_track_id: str):
        await asyncio.sleep(0.1)
        return dict(FAKE_RECCOBEATS_FEATURES)

    with patch("app.vibe_service.get_track_vibe", side_effect=slow_vibe):
        tracks = [(f"track-{i}", None) for i in range(6)]
        start = time.monotonic()
        result = asyncio.run(get_or_compute_vibes_bulk(session, tracks))
        elapsed = time.monotonic() - start

    assert len(result) == 6
    assert all(vibe is not None for vibe in result.values())
    # sequential would take ~0.6s (6 * 0.1s); concurrent stays close to 0.1s
    assert elapsed < 0.3


def test_bulk_lookup_returns_none_for_tracks_with_no_data(session):
    with patch(
        "app.vibe_service.get_track_vibe", new_callable=AsyncMock, return_value=None
    ):
        result = asyncio.run(
            get_or_compute_vibes_bulk(session, [("track-no-data", None)])
        )

    assert result == {"track-no-data": None}
    assert session.get(TrackVibe, "track-no-data") is None

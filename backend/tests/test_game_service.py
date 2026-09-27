import asyncio

import pytest
from sqlmodel import Session

from app.database import get_engine
from app.game_service import (
    NoSuitableAlbumError,
    RoundNotFinishedError,
    reveal_round,
    start_round,
    submit_guess,
)
from app.models import GameRound
from app.schemas import VibeOut

ARTIST = {"id": "artist-1", "name": "Test Artist"}


@pytest.fixture()
def session(client):
    # `client` fixture (from conftest) already calls init_db() against the
    # shared in memory sqlite engine
    with Session(get_engine()) as db_session:
        yield db_session


class FakeSpotifyClient:
    """minimal stand in for SpotifyClient, game_service only needs these
    async methods, so tests can skip http mocking entirely"""

    def __init__(self, albums: list[dict], tracks_by_album: dict[str, list[dict]]):
        self._albums = albums
        self._tracks_by_album = tracks_by_album

    async def get_artist(self, artist_id: str) -> dict:
        return ARTIST

    async def search_artist(self, name: str) -> dict:
        return {"artists": {"items": [ARTIST]}}

    async def search_artists(self, query: str, limit: int = 10) -> dict:
        return {"artists": {"items": [ARTIST]}}

    async def get_artist_albums(self, artist_id: str, limit: int = 50) -> dict:
        return {"items": self._albums}

    async def get_album_tracks(self, album_id: str, limit: int = 50) -> dict:
        return {"items": self._tracks_by_album[album_id]}


def _album(album_id: str, name: str) -> dict:
    return {"id": album_id, "name": name, "album_type": "album", "images": []}


def _track_item(track_id: str, number: int) -> dict:
    return {
        "id": track_id,
        "name": f"Secret Track {number} ({track_id})",
        "track_number": number,
        "preview_url": None,
    }


def _good_vibe(**overrides) -> VibeOut:
    base = dict(
        vibe_score=0.5,
        energy=0.5,
        brightness=0.5,
        tempo_bpm=120.0,
        source="reccobeats",
        danceability=0.6,
        acousticness=0.3,
        instrumentalness=0.1,
        speechiness=0.05,
        loudness=-7.0,
        key=4,
        mode=1,
    )
    base.update(overrides)
    return VibeOut(**base)


def _bulk_vibe_fake(vibe_by_track: dict[str, VibeOut | None] | None = None, default=None):
    """builds a fake for get_or_compute_vibes_bulk, with no args, every
    track gets `default` (none); pass vibe_by_track to look values up per
    track id, falling back to `default` for anything not listed"""

    async def fake(session, tracks):
        lookup = vibe_by_track or {}
        return {track_id: lookup.get(track_id, default) for track_id, _ in tracks}

    return fake


def test_sparse_target_is_rerolled_for_a_better_album(session, monkeypatch):
    monkeypatch.setattr("app.game_service.random.shuffle", lambda seq: None)

    albums = [
        _album("sparse-a", "Sparse Album"),
        _album("sparse-b", "Also Sparse"),
        _album("good-c", "Good Album"),
    ]
    tracks_by_album = {
        "sparse-a": [_track_item("sa1", 1), _track_item("sa2", 2)],
        "sparse-b": [_track_item("sb1", 1), _track_item("sb2", 2)],
        "good-c": [_track_item("gc1", 1), _track_item("gc2", 2)],
    }
    vibe_by_track = {"gc1": _good_vibe(), "gc2": _good_vibe()}

    monkeypatch.setattr(
        "app.game_service.get_or_compute_vibes_bulk", _bulk_vibe_fake(vibe_by_track)
    )

    client_stub = FakeSpotifyClient(albums, tracks_by_album)
    result = asyncio.run(start_round(session, client_stub, "Test Artist"))

    row = session.get(GameRound, result.round_id)
    assert row.target_album_id == "good-c"
    # the sparse albums were tried and rejected, not just skipped, confirm
    # the round still lists all three as guessable options
    option_names = {option["name"] for option in result.album_options}
    assert option_names == {"Sparse Album", "Also Sparse", "Good Album"}


def test_no_album_has_enough_data_raises(session, monkeypatch):
    monkeypatch.setattr("app.game_service.random.shuffle", lambda seq: None)
    albums = [_album("a", "A"), _album("b", "B"), _album("c", "C")]
    tracks_by_album = {
        "a": [_track_item("a1", 1), _track_item("a2", 2)],
        "b": [_track_item("b1", 1), _track_item("b2", 2)],
        "c": [_track_item("c1", 1), _track_item("c2", 2)],
    }

    monkeypatch.setattr("app.game_service.get_or_compute_vibes_bulk", _bulk_vibe_fake())
    client_stub = FakeSpotifyClient(albums, tracks_by_album)

    with pytest.raises(NoSuitableAlbumError):
        asyncio.run(start_round(session, client_stub, "Test Artist"))


def test_filters_out_live_remix_and_reissue_albums_and_dedupes_reissues(session, monkeypatch):
    monkeypatch.setattr("app.game_service.random.shuffle", lambda seq: None)

    # mirrors what spotify's real artist albums endpoint returns for daft
    # punk `album_type=album` alone lets live albums, remixes, and reissue/
    # anniversary editions through alongside the real studio albums
    albums = [
        _album("ram-anniv", "Random Access Memories (10th Anniversary Edition)"),
        _album("homework", "Homework"),
        _album("ram", "Random Access Memories"),
        _album("collab", "Daft Punk | Random Access Memories | The Collaborators"),
        _album("discovery", "Discovery"),
        _album("alive-2007", "Alive 2007"),
        _album("remixes", "Human After All (Remixes)"),
        _album("human-after-all", "Human After All"),
        _album("homework-anniv", "Homework (25th Anniversary Edition)"),
        _album("ram-drumless", "Random Access Memories (Drumless Edition)"),
    ]
    tracks_by_album = {
        album["id"]: [_track_item(f"{album['id']}-t1", 1)] for album in albums
    }

    monkeypatch.setattr(
        "app.game_service.get_or_compute_vibes_bulk", _bulk_vibe_fake(default=_good_vibe())
    )
    client_stub = FakeSpotifyClient(albums, tracks_by_album)
    result = asyncio.run(start_round(session, client_stub, "Daft Punk"))

    option_names = {option["name"] for option in result.album_options}
    assert option_names == {"Homework", "Random Access Memories", "Discovery", "Human After All"}


def test_filters_out_albums_whose_only_non_studio_signal_is_in_track_names(session, monkeypatch):
    """regression test shaped after real cases caught live for radiohead
    the album's own title gives zero hint it's nonstudio, but its track
    names do, "i might be wrong" is radiohead's actual live album, its
    title has no live related keyword, but every track says "- live in
    <city>". "ok computer oknotok 1997 2017" is an anniversary reissue whose
    tracks say "- remastered" rather than "anniversary". "tkol rmx 1234567"
    is a remix album whose tracks say "Remix"/"Rmx" """
    monkeypatch.setattr("app.game_service.random.shuffle", lambda seq: None)

    albums = [
        _album("in-rainbows", "In Rainbows"),
        _album("kid-a", "Kid A"),
        _album("ok-computer", "OK Computer"),
        _album("i-might-be-wrong", "I Might Be Wrong"),
        _album("oknotok", "OK Computer OKNOTOK 1997 2017"),
        _album("tkol-rmx", "TKOL RMX 1234567"),
    ]
    tracks_by_album = {
        "in-rainbows": [_track_item("ir1", 1)],
        "kid-a": [_track_item("ka1", 1)],
        "ok-computer": [_track_item("oc1", 1)],
        "i-might-be-wrong": [
            {
                "id": "imbw1",
                "name": "The National Anthem - Live in France",
                "track_number": 1,
                "preview_url": None,
            },
        ],
        "oknotok": [
            {"id": "ok1", "name": "Airbag - Remastered", "track_number": 1, "preview_url": None},
        ],
        "tkol-rmx": [
            {
                "id": "rmx1",
                "name": "Little By Little - Caribou Rmx",
                "track_number": 1,
                "preview_url": None,
            },
        ],
    }

    monkeypatch.setattr(
        "app.game_service.get_or_compute_vibes_bulk", _bulk_vibe_fake(default=_good_vibe())
    )
    client_stub = FakeSpotifyClient(albums, tracks_by_album)
    result = asyncio.run(start_round(session, client_stub, "Radiohead"))

    option_names = {option["name"] for option in result.album_options}
    assert option_names == {"In Rainbows", "Kid A", "OK Computer"}


def test_hint_metric_revealed_every_second_wrong_guess(session, monkeypatch):
    monkeypatch.setattr("app.game_service.random.shuffle", lambda seq: None)
    albums = [
        _album("target", "Target Album"),
        _album("wrong-1", "Wrong One"),
        _album("wrong-2", "Wrong Two"),
    ]
    tracks_by_album = {
        "target": [_track_item("t1", 1), _track_item("t2", 2)],
        "wrong-1": [_track_item("w1", 1)],
        "wrong-2": [_track_item("w2", 1)],
    }

    monkeypatch.setattr(
        "app.game_service.get_or_compute_vibes_bulk", _bulk_vibe_fake(default=_good_vibe())
    )
    client_stub = FakeSpotifyClient(albums, tracks_by_album)
    result = asyncio.run(start_round(session, client_stub, "Test Artist"))

    # first wrong guess no hint yet
    guess1 = submit_guess(session, result.round_id, "wrong-1")
    assert guess1.correct is False
    assert guess1.wrong_guess_count == 1
    assert guess1.newly_revealed_metric is None

    # second wrong guess crosses the first threshold -> danceability
    guess2 = submit_guess(session, result.round_id, "wrong-2")
    assert guess2.correct is False
    assert guess2.wrong_guess_count == 2
    assert guess2.newly_revealed_metric is not None
    assert guess2.newly_revealed_metric["metric"] == "danceability"
    assert guess2.newly_revealed_metric["data"] == [
        {"track_number": 1, "value": 0.6, "mode": None},
        {"track_number": 2, "value": 0.6, "mode": None},
    ]

    # third wrong guess no new threshold crossed
    guess3 = submit_guess(session, result.round_id, "wrong-1")
    assert guess3.wrong_guess_count == 3
    assert guess3.newly_revealed_metric is None

    # fourth wrong guess crosses the second threshold -> acousticness
    guess4 = submit_guess(session, result.round_id, "wrong-2")
    assert guess4.wrong_guess_count == 4
    assert guess4.newly_revealed_metric["metric"] == "acousticness"

    # a correct guess ends the round without leaking a hint payload
    correct = submit_guess(session, result.round_id, "target")
    assert correct.correct is True
    assert correct.newly_revealed_metric is None


def test_wrong_guesses_stay_eliminated_cumulatively(session, monkeypatch):
    """regression test a prior bug only reported the most recently guessed
    album as eliminated, so an earlier wrong guess would look guessable
    again. eliminated_album_ids must accumulate for the whole round"""
    monkeypatch.setattr("app.game_service.random.shuffle", lambda seq: None)
    albums = [
        _album("target", "Target Album"),
        _album("wrong-1", "Wrong One"),
        _album("wrong-2", "Wrong Two"),
    ]
    tracks_by_album = {
        "target": [_track_item("t1", 1)],
        "wrong-1": [_track_item("w1", 1)],
        "wrong-2": [_track_item("w2", 1)],
    }

    monkeypatch.setattr(
        "app.game_service.get_or_compute_vibes_bulk", _bulk_vibe_fake(default=_good_vibe())
    )
    client_stub = FakeSpotifyClient(albums, tracks_by_album)
    result = asyncio.run(start_round(session, client_stub, "Test Artist"))

    guess1 = submit_guess(session, result.round_id, "wrong-1")
    assert guess1.eliminated_album_ids == ["wrong-1"]

    guess2 = submit_guess(session, result.round_id, "wrong-2")
    assert set(guess2.eliminated_album_ids) == {"wrong-1", "wrong-2"}

    # guessing the same wrong album again must not duplicate it in the list
    guess3 = submit_guess(session, result.round_id, "wrong-1")
    assert sorted(guess3.eliminated_album_ids) == ["wrong-1", "wrong-2"]


def test_reveal_before_solved_requires_give_up(session, monkeypatch):
    monkeypatch.setattr("app.game_service.random.shuffle", lambda seq: None)
    albums = [
        _album("target", "Target Album"),
        _album("wrong-1", "Wrong One"),
        _album("wrong-2", "Wrong Two"),
    ]
    tracks_by_album = {
        "target": [_track_item("t1", 1)],
        "wrong-1": [_track_item("w1", 1)],
        "wrong-2": [_track_item("w2", 1)],
    }

    monkeypatch.setattr(
        "app.game_service.get_or_compute_vibes_bulk", _bulk_vibe_fake(default=_good_vibe())
    )
    client_stub = FakeSpotifyClient(albums, tracks_by_album)
    result = asyncio.run(start_round(session, client_stub, "Test Artist"))

    with pytest.raises(RoundNotFinishedError):
        reveal_round(session, result.round_id)

    revealed = reveal_round(session, result.round_id, give_up=True)
    assert revealed.album_name == "Target Album"
    assert revealed.tracks[0]["name"] == "Secret Track 1 (t1)"


def test_round_creation_never_leaks_target_or_track_names(session, monkeypatch):
    monkeypatch.setattr("app.game_service.random.shuffle", lambda seq: None)
    albums = [
        _album("target", "Target Album"),
        _album("wrong-1", "Wrong One"),
        _album("wrong-2", "Wrong Two"),
    ]
    tracks_by_album = {
        "target": [_track_item("t1", 1), _track_item("t2", 2)],
        "wrong-1": [_track_item("w1", 1)],
        "wrong-2": [_track_item("w2", 1)],
    }

    monkeypatch.setattr(
        "app.game_service.get_or_compute_vibes_bulk", _bulk_vibe_fake(default=_good_vibe())
    )
    client_stub = FakeSpotifyClient(albums, tracks_by_album)
    result = asyncio.run(start_round(session, client_stub, "Test Artist"))

    # hints must only ever carry track_number + vibe_score, never a name
    for hint in result.hints:
        assert set(hint.keys()) == {"track_number", "vibe_score"}

    # a wrong guess's hint payload must only ever carry track_number/value/mode
    guess = submit_guess(session, result.round_id, "wrong-1")
    guess2 = submit_guess(session, result.round_id, "wrong-2")
    assert guess2.newly_revealed_metric is not None
    for point in guess2.newly_revealed_metric["data"]:
        assert set(point.keys()) == {"track_number", "value", "mode"}

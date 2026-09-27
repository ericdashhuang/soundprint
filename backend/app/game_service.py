"""server side orchestration for the album guessing game

the whole point of this module is that the target album's identity and its
track names must never reach the frontend before a round legitimately ends
a browser can trivially inspect network responses, so if the answer were in
the initial round creation or guess response, the game would be broken on
the first round, `GameRound` (app/models.py) is the only place that data
lives, everything this module hands back for an in progress round
(`RoundStart`, `GuessResult`) must be reviewed against that constraint;
`RevealResult` is the sole exception, and only after `GameRound.solved` (or
an explicit give up) is true

reuses the existing Spotify/vibe pipeline rather than duplicating it -
`SpotifyClient` (app/spotify_client.py) for artist/album/track lookups and
`get_or_compute_vibes_bulk` (app/vibe_service.py) for the per track vibe
metrics, cache included, track data is fetched via the *bulk* helper (not
`get_or_compute_vibe` in a per track loop) specifically because a round can
need vibe data for a whole album, up to 3 candidate albums, if rerolling -
and looping the single track lookup serialized what can be dozens of
reccobeats round trips into a many seconds long request that looked hung to
an end user, see vibe_service.get_or_compute_vibes_bulk's docstring
"""

import asyncio
import json
import random
import re
import uuid
from dataclasses import dataclass
from typing import Protocol

from sqlmodel import Session

from app.models import GameRound
from app.vibe_service import get_or_compute_vibes_bulk

# how many real albums an artist needs before a round is even worth starting
MIN_ALBUMS_FOR_ROUND = 3

# how many candidate albums to try before giving up on finding one with
# enough computed vibe data to make a decent puzzle
MAX_TARGET_ATTEMPTS = 3

# caps how many spotify tracklist requests _filter_out_albums_with_non_studio_tracks
# fires at once, an artist with a normal sized catalog (radiohead scale, ~15 to 20
# studio albums after filtering) firing one request per album with no cap was
# enough to trip spotify's real short window rate limit on every round start -
# confirmed live, SpotifyClient retries a single 429'd request on its own
# (see spotify_client.py), but that doesn't help if the burst itself is what
# causes the 429s; keeping the number of simultaneous requests small avoids
# tripping the limit in the first place
_MAX_CONCURRENT_ALBUM_TRACK_FETCHES = 4

# an album qualifies as a target only if at least this fraction of its
# tracks have some computed vibe data (from either reccobeats or librosa)
MIN_VIBE_COVERAGE = 0.5

# every 2nd wrong guess reveals the next metric in this order, Energy/valence
# (the base vibe score line) is visible from the start and is not part of
# this reveal sequence
HINT_METRIC_ORDER = [
    "danceability",
    "acousticness",
    "instrumentalness",
    "speechiness",
    "loudness",
    "key",
]


class ArtistNotFoundError(Exception):
    """no spotify artist matched the given name"""


class NotEnoughAlbumsError(Exception):
    """the artist doesn't have enough real studio albums for a round"""


class NoSuitableAlbumError(Exception):
    """no candidate album had enough computed vibe data for a round"""


class RoundNotFoundError(Exception):
    """no GameRound exists with the given id"""


class RoundNotFinishedError(Exception):
    """reveal was requested before the round was solved (and no give up)"""


class SpotifyClientProtocol(Protocol):
    """the subset of SpotifyClient this module depends on, lets tests pass
    a lightweight stub instead of a real http backed client"""

    async def get_artist(self, artist_id: str) -> dict: ...

    async def search_artist(self, name: str) -> dict: ...

    async def search_artists(self, query: str, limit: int = 10) -> dict: ...

    async def get_artist_albums(self, artist_id: str, limit: int = 50) -> dict: ...

    async def get_album_tracks(self, album_id: str, limit: int = 50) -> dict: ...


# `album_type=album` (via spotify's `include_groups=album`) still lets through
# live albums, remix albums, and deluxe/anniversary/reissue editions, all
# observed live for daft punk (eg "alive 2007", "human after all
# (remixes)", "homework (25th anniversary edition)", "tron legacy
# reconfigured"), a name pattern heuristic filters those out; it's not a
# perfect classifier, but it removes the worst, most obviously nonstudio
# offenders, `|` is a strong signal of a compilation style title (observed
# "daft punk | random access memories | the collaborators")
#
# this same pattern list is also checked against each candidate album's own
# track names (see _filter_out_albums_with_non_studio_tracks), some editions
# give no hint in the album title itself, confirmed live for radiohead
# "i might be wrong" is their actual live album, but the title alone has no
# live related keyword, every track is titled "<song>, live in <city>"
# "remaster" is here for the same reason "ok computer oknotok 1997 2017"'s
# title doesn't say so, but nearly every track is "<song>, remastered"
_NON_STUDIO_NAME_PATTERNS = (
    "live",  # also matches stylized "alive 1997/2007", which are live albums
    "remix",
    "rmx",
    "rework",
    "remaster",
    "anniversary",
    "reconfigured",
    "deluxe",
    "drumless",
    "reissue",
    "the collaborators",
)


def _looks_like_non_studio_edition(name: str) -> bool:
    if "|" in name:
        return True
    lowered = name.lower()
    return any(pattern in lowered for pattern in _NON_STUDIO_NAME_PATTERNS)


def _base_album_name(name: str) -> str:
    """strip parenthetical and trailing ", <descriptor>" suffixes so
    reissues of the same core album collapse onto one canonical entry, eg
    "random access memories (10th anniversary edition)" and "random access
    memories (drumless edition)" both reduce to "random access memories" """
    without_parens = re.sub(r"\s*\([^)]*\)\s*", " ", name)
    without_suffix = re.split(r"\s+-\s+", without_parens)[0]
    return without_suffix.strip().lower()


def _dedupe_albums_by_base_name(items: list[dict]) -> list[dict]:
    """collapse near duplicate reissues of the same base album into one
    entry, the shortest name in each group, since edition descriptors only
    ever add to the plain title, never shorten it"""
    order: list[str] = []
    best_by_key: dict[str, dict] = {}
    for item in items:
        key = _base_album_name(item["name"])
        if key not in best_by_key:
            best_by_key[key] = item
            order.append(key)
        elif len(item["name"]) < len(best_by_key[key]["name"]):
            best_by_key[key] = item
    return [best_by_key[key] for key in order]


async def _filter_out_albums_with_non_studio_tracks(
    client: SpotifyClientProtocol, albums: list[dict]
) -> list[dict]:
    """album title filtering alone misses editions whose own name gives no
    hint (see _NON_STUDIO_NAME_PATTERNS' docstring, "i might be wrong")
    fetches each remaining candidate's tracklist concurrently, capped at
    _MAX_CONCURRENT_ALBUM_TRACK_FETCHES at a time, to avoid both reintroducing
    the sequential network call slowdown fixed in
    vibe_service.get_or_compute_vibes_bulk and tripping spotify's rate limit
    by firing an unbounded burst of simultaneous requests, excludes any
    album where at least one track name matches the same exclude patterns"""
    if not albums:
        return albums

    semaphore = asyncio.Semaphore(_MAX_CONCURRENT_ALBUM_TRACK_FETCHES)

    async def _fetch(album: dict) -> dict:
        async with semaphore:
            return await client.get_album_tracks(album["id"])

    track_pages = await asyncio.gather(*(_fetch(album) for album in albums))

    kept = []
    for album, tracks_page in zip(albums, track_pages):
        track_names = [item["name"] for item in tracks_page.get("items", [])]
        if any(_looks_like_non_studio_edition(name) for name in track_names):
            continue
        kept.append(album)
    return kept


async def _fetch_real_albums(client: SpotifyClientProtocol, artist_id: str) -> list[dict]:
    page = await client.get_artist_albums(artist_id)
    albums = [item for item in page.get("items", []) if item.get("album_type") == "album"]
    albums = [item for item in albums if not _looks_like_non_studio_edition(item["name"])]
    albums = await _filter_out_albums_with_non_studio_tracks(client, albums)
    return _dedupe_albums_by_base_name(albums)


async def _build_track_data(
    session: Session, client: SpotifyClientProtocol, album_id: str
) -> list[dict]:
    tracks_page = await client.get_album_tracks(album_id)
    items = tracks_page["items"]
    vibes = await get_or_compute_vibes_bulk(
        session, [(item["id"], item.get("preview_url")) for item in items]
    )
    tracks = []
    for item in items:
        vibe = vibes[item["id"]]
        tracks.append(
            {
                "spotify_id": item["id"],
                "name": item["name"],
                "track_number": item["track_number"],
                "vibe": vibe.model_dump() if vibe else None,
            }
        )
    return tracks


def _vibe_coverage(tracks: list[dict]) -> float:
    if not tracks:
        return 0.0
    with_vibe = sum(1 for track in tracks if track["vibe"] is not None)
    return with_vibe / len(tracks)


def _album_image_url(album: dict) -> str | None:
    images = album.get("images") or []
    return images[0]["url"] if images else None


@dataclass
class ArtistSuggestion:
    spotify_id: str
    name: str
    image_url: str | None


async def search_artists(
    client: SpotifyClientProtocol, query: str, limit: int = 5
) -> list[ArtistSuggestion]:
    """backs the artist name autocomplete dropdown, a thin pass through
    over spotify's own artist search, trimmed to the fields the frontend
    needs (name + image) plus the exact spotify id so selecting a suggestion
    can start a round unambiguously via `start_round(artist_spotify_id=...)`
    """
    query = query.strip()
    if not query:
        return []
    result = await client.search_artists(query, limit=limit)
    items = result.get("artists", {}).get("items", [])
    return [
        ArtistSuggestion(
            spotify_id=item["id"], name=item["name"], image_url=_album_image_url(item)
        )
        for item in items
    ]


@dataclass
class RoundStart:
    round_id: str
    artist_name: str
    album_options: list[dict]
    track_count: int
    hints: list[dict]


async def start_round(
    session: Session,
    client: SpotifyClientProtocol,
    artist_name: str | None = None,
    artist_spotify_id: str | None = None,
) -> RoundStart:
    """resolve an artist and start a round in one call

    prefers `artist_spotify_id` when given, the autocomplete dropdown
    passes the exact artist the player selected, which avoids the
    ambiguous name mismatches a plain name search can hit (two artists can
    legitimately share a name), falls back to a name search otherwise

    picks a random target album, rerolling (bounded by MAX_TARGET_ATTEMPTS)
    if the chosen one has too little computed vibe data to make a decent
    puzzle, raises ArtistNotFoundError / NotEnoughAlbumsError /
    NoSuitableAlbumError for the corresponding failure cases, see
    app/main.py for how those map to http responses
    """
    if artist_spotify_id:
        artist = await client.get_artist(artist_spotify_id)
    else:
        if not artist_name or not artist_name.strip():
            raise ArtistNotFoundError("An artist name is required.")
        search = await client.search_artist(artist_name)
        artists = search.get("artists", {}).get("items", [])
        if not artists:
            raise ArtistNotFoundError(f"No Spotify artist found for '{artist_name}'.")
        artist = artists[0]

    albums = await _fetch_real_albums(client, artist["id"])
    if len(albums) < MIN_ALBUMS_FOR_ROUND:
        raise NotEnoughAlbumsError(
            f"{artist['name']} doesn't have enough real studio albums for a round."
        )

    candidates = albums.copy()
    random.shuffle(candidates)

    target_album: dict | None = None
    target_tracks: list[dict] | None = None
    for album in candidates[:MAX_TARGET_ATTEMPTS]:
        tracks = await _build_track_data(session, client, album["id"])
        if _vibe_coverage(tracks) >= MIN_VIBE_COVERAGE:
            target_album = album
            target_tracks = tracks
            break

    if target_album is None or target_tracks is None:
        raise NoSuitableAlbumError(
            f"Couldn't find an album from {artist['name']} with enough vibe data for a round."
        )

    round_id = uuid.uuid4().hex
    options = [{"spotify_id": album["id"], "name": album["name"]} for album in albums]
    random.shuffle(options)

    row = GameRound(
        id=round_id,
        artist_name=artist["name"],
        target_album_id=target_album["id"],
        target_album_name=target_album["name"],
        target_album_image_url=_album_image_url(target_album),
        tracks_json=json.dumps(target_tracks),
        album_options_json=json.dumps(options),
    )
    session.add(row)
    session.commit()

    ordered_tracks = sorted(target_tracks, key=lambda t: t["track_number"])
    hints = [
        {
            "track_number": track["track_number"],
            "vibe_score": (track["vibe"] or {}).get("vibe_score"),
        }
        for track in ordered_tracks
    ]

    return RoundStart(
        round_id=round_id,
        artist_name=artist["name"],
        album_options=options,
        track_count=len(target_tracks),
        hints=hints,
    )


def _get_round(session: Session, round_id: str) -> GameRound:
    row = session.get(GameRound, round_id)
    if row is None:
        raise RoundNotFoundError(f"No active round with id {round_id}.")
    return row


@dataclass
class GuessResult:
    correct: bool
    wrong_guess_count: int
    eliminated_album_ids: list[str]
    newly_revealed_metric: dict | None


def submit_guess(session: Session, round_id: str, guessed_album_id: str) -> GuessResult:
    """check a guess server side and, on a wrong guess, cross any newly
    unlocked hint threshold, never returns the target's identity or any
    track name, even on a correct guess, that's reveal_round's job

    the set of eliminated (wrong guessed) album ids is tracked here, in
    `GameRound.eliminated_album_ids_json`, and returned in full on every
    call, the frontend should treat this list as authoritative rather than
    accumulating its own, so a lost or out of order response can never leave
    a previously wrong guessed album looking guessable again
    """
    row = _get_round(session, round_id)
    eliminated: list[str] = json.loads(row.eliminated_album_ids_json)

    if row.solved or guessed_album_id == row.target_album_id:
        row.solved = True
        session.add(row)
        session.commit()
        return GuessResult(
            correct=True,
            wrong_guess_count=row.wrong_guess_count,
            eliminated_album_ids=eliminated,
            newly_revealed_metric=None,
        )

    if guessed_album_id not in eliminated:
        eliminated.append(guessed_album_id)
        row.eliminated_album_ids_json = json.dumps(eliminated)

    row.wrong_guess_count += 1
    new_hint_level = min(row.wrong_guess_count // 2, len(HINT_METRIC_ORDER))

    newly_revealed = None
    if new_hint_level > row.revealed_hint_level:
        metric_name = HINT_METRIC_ORDER[new_hint_level - 1]
        tracks = sorted(json.loads(row.tracks_json), key=lambda t: t["track_number"])
        newly_revealed = {
            "metric": metric_name,
            "data": [
                {
                    "track_number": track["track_number"],
                    "value": (track["vibe"] or {}).get(metric_name),
                    "mode": (track["vibe"] or {}).get("mode") if metric_name == "key" else None,
                }
                for track in tracks
            ],
        }
        row.revealed_hint_level = new_hint_level

    session.add(row)
    session.commit()

    return GuessResult(
        correct=False,
        wrong_guess_count=row.wrong_guess_count,
        eliminated_album_ids=eliminated,
        newly_revealed_metric=newly_revealed,
    )


@dataclass
class RevealResult:
    album_name: str
    album_image_url: str | None
    artist_name: str
    tracks: list[dict]
    revealed_metrics: list[str]


def reveal_round(session: Session, round_id: str, give_up: bool = False) -> RevealResult:
    """reveal a round's answer, callable once the round is solved, or with
    `give_up=True` to end it early without a correct guess"""
    row = _get_round(session, round_id)

    if not row.solved:
        if not give_up:
            raise RoundNotFinishedError("This round hasn't been solved yet.")
        row.solved = True
        session.add(row)
        session.commit()

    tracks = sorted(json.loads(row.tracks_json), key=lambda t: t["track_number"])
    revealed_metrics = list(HINT_METRIC_ORDER)

    def _track_out(track: dict) -> dict:
        vibe = track["vibe"] or {}
        out = {
            "track_number": track["track_number"],
            "name": track["name"],
            "vibe_score": vibe.get("vibe_score"),
        }
        for metric in revealed_metrics:
            out[metric] = vibe.get(metric)
        if "key" in revealed_metrics:
            out["mode"] = vibe.get("mode")
        return out

    return RevealResult(
        album_name=row.target_album_name,
        album_image_url=row.target_album_image_url,
        artist_name=row.artist_name,
        tracks=[_track_out(t) for t in tracks],
        revealed_metrics=revealed_metrics,
    )

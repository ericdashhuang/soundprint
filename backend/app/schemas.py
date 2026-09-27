from pydantic import BaseModel


class VibeOut(BaseModel):
    """computed vibe/energy signal for one track, `source` distinguishes which
    pipeline produced it, see app/vibe_service.py for the lookup order and
    app/reccobeats_client.py / app/vibe_analysis.py for how each is derived

    the fields below `tempo_bpm` are only ever populated from reccobeats, the
    librosa fallback has no equivalent signal for them, so a track whose vibe
    came from librosa will have all of them as none, consumers (the game
    pipeline in particular) must treat their absence as "no data for this
    track", not an error
    """

    vibe_score: float
    energy: float
    brightness: float
    tempo_bpm: float
    source: str
    danceability: float | None = None
    acousticness: float | None = None
    instrumentalness: float | None = None
    speechiness: float | None = None
    loudness: float | None = None
    key: int | None = None
    mode: int | None = None


class TrackOut(BaseModel):
    spotify_id: str
    name: str
    artist: str
    duration_ms: int
    track_number: int
    preview_url: str | None = None
    vibe: VibeOut | None = None


class LookupResult(BaseModel):
    item_type: str
    spotify_id: str
    name: str
    owner: str  # artist name for an album, or playlist owner's display name for a playlist
    cover_art_url: str | None
    tracks: list[TrackOut]


# --- album guessing game -----------------------------------------------------
#
# these schemas back the game endpoints in app/main.py / app/game_service.py
# the one rule that matters across all of them none of the "in progress
# round" shapes (StartRoundResponse, GuessResponse) may carry the target
# album's identity or any track name, only RevealResponse may, and only
# after a round is solved (or the player gives up), see app/game_service.py's
# module docstring for why


class StartRoundRequest(BaseModel):
    # `artist_spotify_id` (set when the player picked a suggestion from the
    # autocomplete dropdown) takes priority over `artist_name` when both are
    # present, see game_service.start_round, at least one must be set
    artist_name: str | None = None
    artist_spotify_id: str | None = None


class ArtistSuggestion(BaseModel):
    spotify_id: str
    name: str
    image_url: str | None = None


class AlbumOption(BaseModel):
    spotify_id: str
    name: str


class HintPoint(BaseModel):
    track_number: int
    vibe_score: float | None


class StartRoundResponse(BaseModel):
    round_id: str
    artist_name: str
    album_options: list[AlbumOption]
    track_count: int
    hints: list[HintPoint]


class GuessRequest(BaseModel):
    album_spotify_id: str


class MetricPoint(BaseModel):
    track_number: int
    value: float | None
    mode: int | None = None  # only meaningful when the metric is "key"


class RevealedMetric(BaseModel):
    metric: str
    data: list[MetricPoint]


class GuessResponse(BaseModel):
    correct: bool
    wrong_guess_count: int
    # authoritative, cumulative list of every album id guessed wrong so far
    # this round, the frontend should render eliminated options from this,
    # not from its own accumulated local state
    eliminated_album_ids: list[str]
    newly_revealed_metric: RevealedMetric | None = None


class RevealedTrack(BaseModel):
    track_number: int
    name: str
    vibe_score: float | None
    danceability: float | None = None
    acousticness: float | None = None
    instrumentalness: float | None = None
    speechiness: float | None = None
    loudness: float | None = None
    key: int | None = None
    mode: int | None = None


class RevealResponse(BaseModel):
    album_name: str
    album_image_url: str | None
    artist_name: str
    tracks: list[RevealedTrack]
    revealed_metrics: list[str]

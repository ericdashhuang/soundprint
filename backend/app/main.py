from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlmodel import Session

from app.config import Settings, get_settings
from app.database import get_session, init_db
from app.game_service import (
    ArtistNotFoundError,
    NoSuitableAlbumError,
    NotEnoughAlbumsError,
    RoundNotFinishedError,
    RoundNotFoundError,
    reveal_round,
    search_artists,
    start_round,
    submit_guess,
)
from app.lookup import build_lookup_result
from app.models import LookupLog
from app.schemas import (
    AlbumOption,
    ArtistSuggestion,
    GuessRequest,
    GuessResponse,
    HintPoint,
    LookupResult,
    RevealedMetric,
    RevealedTrack,
    RevealResponse,
    StartRoundRequest,
    StartRoundResponse,
)
from app.spotify_client import (
    SpotifyApiError,
    SpotifyAuthError,
    SpotifyClient,
    SpotifyNotFoundError,
    SpotifyRateLimitedError,
)
from app.url_parsing import InvalidSpotifyUrlError, parse_spotify_reference
from app.vibe_service import get_or_compute_vibe
from app.warmup import warm_up_external_clients


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    settings = get_settings()
    if settings.warm_up_on_startup:
        await warm_up_external_clients(settings)
    yield


app = FastAPI(title="SoundPrint API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origin_list,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


def get_spotify_client(settings: Settings = Depends(get_settings)) -> SpotifyClient:
    return SpotifyClient(settings)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/lookup", response_model=LookupResult)
async def lookup(
    url: str = Query(..., description="A Spotify album or playlist URL or URI"),
    session: Session = Depends(get_session),
) -> LookupResult:
    ref = parse_spotify_reference(url)

    settings = get_settings()
    client = SpotifyClient(settings)
    try:
        result = await build_lookup_result(client, ref)
    finally:
        await client.aclose()

    for track in result.tracks:
        track.vibe = await get_or_compute_vibe(session, track.spotify_id, track.preview_url)

    session.add(
        LookupLog(item_type=result.item_type, spotify_id=result.spotify_id, name=result.name)
    )
    session.commit()

    return result


@app.get("/api/game/artists", response_model=list[ArtistSuggestion])
async def search_game_artists(
    q: str = Query(..., min_length=1, description="Partial artist name"),
) -> list[ArtistSuggestion]:
    settings = get_settings()
    client = SpotifyClient(settings)
    try:
        results = await search_artists(client, q)
    finally:
        await client.aclose()

    return [
        ArtistSuggestion(spotify_id=r.spotify_id, name=r.name, image_url=r.image_url)
        for r in results
    ]


@app.post("/api/game/rounds", response_model=StartRoundResponse)
async def start_game_round(
    request: StartRoundRequest, session: Session = Depends(get_session)
) -> StartRoundResponse:
    settings = get_settings()
    client = SpotifyClient(settings)
    try:
        result = await start_round(
            session,
            client,
            artist_name=request.artist_name,
            artist_spotify_id=request.artist_spotify_id,
        )
    finally:
        await client.aclose()

    return StartRoundResponse(
        round_id=result.round_id,
        artist_name=result.artist_name,
        album_options=[AlbumOption(**option) for option in result.album_options],
        track_count=result.track_count,
        hints=[HintPoint(**hint) for hint in result.hints],
    )


@app.post("/api/game/rounds/{round_id}/guess", response_model=GuessResponse)
def submit_round_guess(
    round_id: str, request: GuessRequest, session: Session = Depends(get_session)
) -> GuessResponse:
    result = submit_guess(session, round_id, request.album_spotify_id)
    return GuessResponse(
        correct=result.correct,
        wrong_guess_count=result.wrong_guess_count,
        eliminated_album_ids=result.eliminated_album_ids,
        newly_revealed_metric=(
            RevealedMetric(**result.newly_revealed_metric)
            if result.newly_revealed_metric
            else None
        ),
    )


@app.post("/api/game/rounds/{round_id}/reveal", response_model=RevealResponse)
def reveal_game_round(
    round_id: str,
    give_up: bool = Query(False, description="Reveal the answer without a correct guess"),
    session: Session = Depends(get_session),
) -> RevealResponse:
    result = reveal_round(session, round_id, give_up=give_up)
    return RevealResponse(
        album_name=result.album_name,
        album_image_url=result.album_image_url,
        artist_name=result.artist_name,
        tracks=[RevealedTrack(**track) for track in result.tracks],
        revealed_metrics=result.revealed_metrics,
    )


@app.exception_handler(InvalidSpotifyUrlError)
async def invalid_url_handler(request, exc: InvalidSpotifyUrlError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(SpotifyNotFoundError)
async def not_found_handler(request, exc: SpotifyNotFoundError):
    return JSONResponse(
        status_code=404,
        content={"detail": "That album or playlist could not be found on Spotify."},
    )


@app.exception_handler(SpotifyRateLimitedError)
async def rate_limited_handler(request, exc: SpotifyRateLimitedError):
    headers = {"Retry-After": str(exc.retry_after_seconds)} if exc.retry_after_seconds else {}
    return JSONResponse(
        status_code=429,
        content={"detail": "Spotify rate limit exceeded. Please try again shortly."},
        headers=headers,
    )


@app.exception_handler(SpotifyAuthError)
async def auth_error_handler(request, exc: SpotifyAuthError):
    return JSONResponse(
        status_code=502,
        content={"detail": "Could not authenticate with Spotify. Check server configuration."},
    )


@app.exception_handler(SpotifyApiError)
async def generic_spotify_error_handler(request, exc: SpotifyApiError):
    return JSONResponse(
        status_code=502,
        content={"detail": "Spotify returned an unexpected error. Please try again."},
    )


@app.exception_handler(ArtistNotFoundError)
async def artist_not_found_handler(request, exc: ArtistNotFoundError):
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(NotEnoughAlbumsError)
async def not_enough_albums_handler(request, exc: NotEnoughAlbumsError):
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.exception_handler(NoSuitableAlbumError)
async def no_suitable_album_handler(request, exc: NoSuitableAlbumError):
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.exception_handler(RoundNotFoundError)
async def round_not_found_handler(request, exc: RoundNotFoundError):
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(RoundNotFinishedError)
async def round_not_finished_handler(request, exc: RoundNotFinishedError):
    return JSONResponse(status_code=409, content={"detail": str(exc)})

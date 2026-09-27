import asyncio
import time
from urllib.parse import quote

import httpx

from app.config import Settings

TOKEN_URL = "https://accounts.spotify.com/api/token"
API_BASE = "https://api.spotify.com/v1"

# refresh a little before actual expiry to avoid racing a request against the deadline
_EXPIRY_SAFETY_MARGIN_SECONDS = 30

# a 429 from spotify is retried this many times (the initial attempt plus
# this many extra tries) before giving up and raising SpotifyRateLimitedError
# confirmed live spotify's real rate limit here is short lived and trips on
# request *bursts* (see game_service._filter_out_albums_with_non_studio_tracks),
# not a sustained multihour block, a single retry after backing off almost
# always succeeds
_MAX_RATE_LIMIT_RETRIES = 3

# used only when a 429 response has no retry after header
_DEFAULT_RATE_LIMIT_BACKOFF_SECONDS = 2.0

# retry after is honored as is up to this ceiling, confirmed live a 429
# triggered on a request pattern spotify treats as abusive (eg the same
# request retried repeatedly with no backoff) can carry a retry after in the
# tens of thousands of seconds, sleeping that long inside a request handler
# would hang it for hours, which is worse for users than surfacing the error
# the short lived burst limit this retry exists for reports a retry after of
# at most a few seconds, well under this ceiling
_MAX_RATE_LIMIT_BACKOFF_SECONDS = 10.0


class SpotifyApiError(Exception):
    """base class for errors surfaced from the spotify web api"""


class SpotifyNotFoundError(SpotifyApiError):
    pass


class SpotifyRateLimitedError(SpotifyApiError):
    def __init__(self, retry_after_seconds: int | None = None):
        super().__init__("Spotify rate limit exceeded.")
        self.retry_after_seconds = retry_after_seconds


class SpotifyAuthError(SpotifyApiError):
    pass


class SpotifyClient:
    """thin async client for the spotify web api, authenticated via the
    client credentials flow (app level access, no user login involved)
    """

    def __init__(self, settings: Settings, http_client: httpx.AsyncClient | None = None):
        self._settings = settings
        self._http = http_client or httpx.AsyncClient(timeout=10.0)
        self._token: str | None = None
        self._token_expires_at: float = 0.0

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _get_access_token(self) -> str:
        if self._token and time.monotonic() < self._token_expires_at:
            return self._token

        response = await self._http.post(
            TOKEN_URL,
            data={"grant_type": "client_credentials"},
            auth=(self._settings.spotify_client_id, self._settings.spotify_client_secret),
        )
        if response.status_code != 200:
            raise SpotifyAuthError(
                f"Failed to obtain Spotify access token (status {response.status_code})."
            )

        payload = response.json()
        self._token = payload["access_token"]
        expires_in = payload.get("expires_in", 3600)
        self._token_expires_at = time.monotonic() + expires_in - _EXPIRY_SAFETY_MARGIN_SECONDS
        return self._token

    async def _handle_response(self, response: httpx.Response, description: str) -> dict:
        if response.status_code == 404:
            raise SpotifyNotFoundError(f"Spotify resource not found: {description}")
        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After")
            raise SpotifyRateLimitedError(int(retry_after) if retry_after else None)
        response.raise_for_status()
        return response.json()

    async def _get_with_retry(self, url: str, description: str) -> dict:
        """get `url` (already fully qualified), retrying a 429 up to
        _MAX_RATE_LIMIT_RETRIES times, this is the single choke point for
        every outgoing spotify request (both `_get` and `_get_absolute` route
        through it) specifically so a concurrent burst of calls, such as
        game_service's per album tracklist fetch, benefits from the same
        backoff as any other call, not just its own call site"""
        token = await self._get_access_token()
        for attempt in range(1, _MAX_RATE_LIMIT_RETRIES + 1):
            response = await self._http.get(url, headers={"Authorization": f"Bearer {token}"})
            try:
                return await self._handle_response(response, description)
            except SpotifyRateLimitedError as exc:
                if attempt == _MAX_RATE_LIMIT_RETRIES:
                    raise
                delay = (
                    min(exc.retry_after_seconds, _MAX_RATE_LIMIT_BACKOFF_SECONDS)
                    if exc.retry_after_seconds is not None
                    else _DEFAULT_RATE_LIMIT_BACKOFF_SECONDS
                )
                await asyncio.sleep(delay)
        raise AssertionError("unreachable")  # loop always returns or raises above

    async def _get(self, path: str) -> dict:
        return await self._get_with_retry(f"{API_BASE}{path}", path)

    async def _get_absolute(self, url: str) -> dict:
        """follow a full url from a paginated response's `next` field"""
        return await self._get_with_retry(url, url)

    async def get_album(self, album_id: str) -> dict:
        return await self._get(f"/albums/{album_id}")

    async def get_album_tracks(self, album_id: str, limit: int = 50) -> dict:
        return await self._get(f"/albums/{album_id}/tracks?limit={limit}")

    async def get_playlist(self, playlist_id: str) -> dict:
        return await self._get(f"/playlists/{playlist_id}")

    async def get_playlist_items(self, playlist_id: str, limit: int = 100) -> dict:
        return await self._get(f"/playlists/{playlist_id}/items?limit={limit}")

    async def get_artist(self, artist_id: str) -> dict:
        return await self._get(f"/artists/{artist_id}")

    async def search_artist(self, name: str) -> dict:
        return await self.search_artists(name, limit=1)

    async def search_artists(self, query: str, limit: int = 10) -> dict:
        return await self._get(f"/search?q={quote(query)}&type=artist&limit={limit}")

    async def get_artist_albums(self, artist_id: str, limit: int = 10) -> dict:
        # include_groups=album excludes singles, compilations, and
        # "appears on" credits, leaving only the artist's real studio albums
        #
        # confirmed live against the real api despite spotify's docs
        # suggesting `limit` can go up to 50 for this endpoint, any value
        # above 10 is rejected with a 400 "invalid limit". pages are
        # followed via the response's `next` link so a prolific artist's
        # full studio catalog is still collected, not just its first 10
        first_page = await self._get(
            f"/artists/{artist_id}/albums?include_groups=album&limit={limit}"
        )
        items = list(first_page.get("items", []))
        next_url = first_page.get("next")
        while next_url:
            page = await self._get_absolute(next_url)
            items.extend(page.get("items", []))
            next_url = page.get("next")
        return {"items": items}

import re
from dataclasses import dataclass
from urllib.parse import urlparse

SUPPORTED_TYPES = {"album", "playlist"}

_SPOTIFY_ID_RE = re.compile(r"^[A-Za-z0-9]{22}$")

_URI_RE = re.compile(r"^spotify:(?P<type>[a-z]+):(?P<id>[A-Za-z0-9]+)$")


class InvalidSpotifyUrlError(ValueError):
    """raised when a pasted string can't be parsed into a spotify album/playlist reference"""


@dataclass(frozen=True)
class SpotifyRef:
    item_type: str
    item_id: str


def parse_spotify_reference(raw: str) -> SpotifyRef:
    """parse a pasted spotify album/playlist url or uri into its type and id

    accepts
      https://open.spotify.com/album/{id}
      https://open.spotify.com/playlist/{id}?si=...
      open.spotify.com/intl-xx/album/{id}  (locale prefixed links)
      spotify:album:{id}
      spotify:playlist:{id}
    """
    if not raw or not raw.strip():
        raise InvalidSpotifyUrlError("URL is empty.")

    value = raw.strip()

    uri_match = _URI_RE.match(value)
    if uri_match:
        return _validate(uri_match.group("type"), uri_match.group("id"))

    parsed = urlparse(value if "://" in value else f"https://{value}")
    if parsed.netloc.lower() not in {"open.spotify.com", "www.open.spotify.com"}:
        raise InvalidSpotifyUrlError(f"'{raw}' is not a recognized Spotify URL or URI.")

    segments = [segment for segment in parsed.path.split("/") if segment]
    # locale prefixed links look like /intl-de/album/{id}; drop a leading "intl-*" segment
    if segments and segments[0].startswith("intl-"):
        segments = segments[1:]

    if len(segments) < 2:
        raise InvalidSpotifyUrlError(f"Could not find an album or playlist ID in '{raw}'.")

    return _validate(segments[0], segments[1])


def _validate(item_type: str, item_id: str) -> SpotifyRef:
    item_type = item_type.lower()
    if item_type not in SUPPORTED_TYPES:
        raise InvalidSpotifyUrlError(
            f"Unsupported Spotify link type '{item_type}'. Only albums and playlists are supported."
        )
    if not _SPOTIFY_ID_RE.match(item_id):
        raise InvalidSpotifyUrlError(f"'{item_id}' doesn't look like a valid Spotify ID.")
    return SpotifyRef(item_type=item_type, item_id=item_id)

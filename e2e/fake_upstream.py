"""a tiny fake of the two third party apis the backend calls spotify and reccobeats

it serves a fixed catalog so the end to end tests are deterministic and need
no spotify credentials, only the routes the backend actually uses exist here
both apis are served from one host; their route prefixes do not collide
(spotify /api/token and /v1/search|artists|albums, reccobeats /v1/track)
"""

import hashlib

from fastapi import FastAPI, HTTPException, Query

ARTISTS = {
    "artist-fake-band": "Fake Band",
    "artist-fake-orchestra": "Fake Orchestra",
}

# album and track names avoid the substrings the backend's studio album filter
# rejects (eg "live", "remix", "deluxe"), so every album counts as a real one
ALBUMS = {
    "album-first-light": ("First Light", ["Opening Bars", "Paper Moon", "Neon Harbor", "Glass Garden"]),
    "album-second-skin": ("Second Skin", ["Quiet Engine", "Amber Road", "Salt Flats", "Copper Sky"]),
    "album-third-coast": ("Third Coast", ["Tidal Map", "Iron Orchard", "Velvet Static", "Blue Ledger"]),
    "album-fourth-wall": ("Fourth Wall", ["Hollow Crown", "Marble Rain", "Night Ferry", "Silver Thread"]),
}

app = FastAPI(title="Fake Spotify and ReccoBeats")


def _track_id(album_id: str, number: int) -> str:
    return f"{album_id}-track-{number}"


def _unit(seed: str, salt: str) -> float:
    """deterministic pseudo random number in [0, 1) derived from the inputs"""
    digest = hashlib.md5(f"{seed}:{salt}".encode()).hexdigest()
    return int(digest[:8], 16) / 0x100000000


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.post("/api/token")
def token() -> dict:
    return {"access_token": "fake-token", "token_type": "Bearer", "expires_in": 3600}


@app.get("/v1/search")
def search(q: str, type: str = "artist", limit: int = 10) -> dict:
    items = [
        {"id": artist_id, "name": name, "images": []}
        for artist_id, name in ARTISTS.items()
        if q.lower() in name.lower()
    ]
    return {"artists": {"items": items[:limit]}}


@app.get("/v1/artists/{artist_id}")
def artist(artist_id: str) -> dict:
    if artist_id not in ARTISTS:
        raise HTTPException(status_code=404)
    return {"id": artist_id, "name": ARTISTS[artist_id], "images": []}


@app.get("/v1/artists/{artist_id}/albums")
def artist_albums(artist_id: str, include_groups: str = "album", limit: int = 10) -> dict:
    if artist_id != "artist-fake-band":
        return {"items": [], "next": None}
    items = [
        {"id": album_id, "name": name, "album_type": "album", "images": []}
        for album_id, (name, _tracks) in ALBUMS.items()
    ]
    return {"items": items, "next": None}


@app.get("/v1/albums/{album_id}/tracks")
def album_tracks(album_id: str, limit: int = 50) -> dict:
    if album_id not in ALBUMS:
        raise HTTPException(status_code=404)
    _name, track_names = ALBUMS[album_id]
    items = [
        {"id": _track_id(album_id, number), "name": name, "track_number": number, "preview_url": None}
        for number, name in enumerate(track_names, start=1)
    ]
    return {"items": items}


@app.get("/v1/track")
def reccobeats_track(ids: str = Query(...)) -> dict:
    return {"content": [{"id": f"rb-{ids}"}]}


@app.get("/v1/track/{reccobeats_id}/audio-features")
def reccobeats_audio_features(reccobeats_id: str) -> dict:
    seed = reccobeats_id
    return {
        "energy": round(_unit(seed, "energy"), 3),
        "valence": round(_unit(seed, "valence"), 3),
        "tempo": round(80 + 80 * _unit(seed, "tempo"), 1),
        "danceability": round(_unit(seed, "danceability"), 3),
        "acousticness": round(_unit(seed, "acousticness"), 3),
        "instrumentalness": round(_unit(seed, "instrumentalness"), 3),
        "speechiness": round(_unit(seed, "speechiness"), 3),
        "loudness": round(-20 + 16 * _unit(seed, "loudness"), 2),
        "key": int(12 * _unit(seed, "key")),
        "mode": int(2 * _unit(seed, "mode")),
    }

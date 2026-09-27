import json
from unittest.mock import patch

import respx
from httpx import Response

TOKEN_RESPONSE = {"access_token": "fake-token", "token_type": "Bearer", "expires_in": 3600}

ARTIST_ID = "artist-xyz"
ALBUM_TARGET = "album-target"
ALBUM_B = "album-b"
ALBUM_C = "album-c"

TARGET_ALBUM_NAME = "Secret Album Name"
SECRET_TRACK_NAMES = ["Secret Track One", "Secret Track Two", "Secret Track Three"]


def _mock_token(router: respx.MockRouter) -> None:
    router.post("https://accounts.spotify.com/api/token").mock(
        return_value=Response(200, json=TOKEN_RESPONSE)
    )


def _mock_search(router: respx.MockRouter) -> None:
    router.get(url__regex=r"https://api\.spotify\.com/v1/search\?.*").mock(
        return_value=Response(
            200, json={"artists": {"items": [{"id": ARTIST_ID, "name": "Test Artist"}]}}
        )
    )


def _mock_albums(router: respx.MockRouter) -> None:
    router.get(url__regex=rf"https://api\.spotify\.com/v1/artists/{ARTIST_ID}/albums.*").mock(
        return_value=Response(
            200,
            json={
                "items": [
                    {
                        "id": ALBUM_TARGET,
                        "name": TARGET_ALBUM_NAME,
                        "album_type": "album",
                        "images": [{"url": "https://example.com/target.jpg"}],
                    },
                    {"id": ALBUM_B, "name": "Other Album", "album_type": "album", "images": []},
                    {"id": ALBUM_C, "name": "Third Album", "album_type": "album", "images": []},
                ]
            },
        )
    )


def _mock_album_tracks(router: respx.MockRouter, album_id: str, tracks: list[dict]) -> None:
    router.get(url__regex=rf"https://api\.spotify\.com/v1/albums/{album_id}/tracks.*").mock(
        return_value=Response(
            200,
            json={
                "items": [
                    {
                        "id": track["id"],
                        "name": track["name"],
                        "artists": [{"name": "Test Artist"}],
                        "duration_ms": 200000,
                        "track_number": i + 1,
                        "preview_url": None,
                    }
                    for i, track in enumerate(tracks)
                ]
            },
        )
    )


def _mock_reccobeats_any(router: respx.MockRouter) -> None:
    router.get(url__regex=r"https://api\.reccobeats\.com/v1/track\?.*").mock(
        return_value=Response(200, json={"content": [{"id": "recco-id"}]})
    )
    router.get(url__regex=r"https://api\.reccobeats\.com/v1/track/.*/audio-features").mock(
        return_value=Response(
            200,
            json={
                "energy": 0.6,
                "valence": 0.5,
                "tempo": 120.0,
                "danceability": 0.7,
                "acousticness": 0.2,
                "instrumentalness": 0.1,
                "speechiness": 0.05,
                "loudness": -6.0,
                "key": 3,
                "mode": 1,
            },
        )
    )


def _setup(router: respx.MockRouter) -> None:
    _mock_token(router)
    _mock_search(router)
    _mock_albums(router)
    _mock_album_tracks(
        router, ALBUM_TARGET, [{"id": f"secret-{i}", "name": name} for i, name in enumerate(SECRET_TRACK_NAMES)]
    )
    _mock_album_tracks(router, ALBUM_B, [{"id": "b1", "name": "B Track"}])
    _mock_album_tracks(router, ALBUM_C, [{"id": "c1", "name": "C Track"}])
    _mock_reccobeats_any(router)


@respx.mock
@patch("app.game_service.random.shuffle", lambda seq: None)
def test_round_lifecycle_never_leaks_target_before_reveal(client):
    _setup(respx)

    start_response = client.post("/api/game/rounds", json={"artist_name": "Test Artist"})
    assert start_response.status_code == 200
    start_body = start_response.json()
    raw_start = json.dumps(start_body)

    # track names must never appear before reveal
    for name in SECRET_TRACK_NAMES:
        assert name not in raw_start
    # the album list legitimately shows all names (that's the whole guessing
    # mechanic) but nothing in the payload may mark which one is correct
    option_names = {option["name"] for option in start_body["album_options"]}
    assert option_names == {TARGET_ALBUM_NAME, "Other Album", "Third Album"}
    assert all(set(hint.keys()) == {"track_number", "vibe_score"} for hint in start_body["hints"])

    round_id = start_body["round_id"]

    # wrong guess #1 no hint yet, still no leakage
    wrong_1 = client.post(f"/api/game/rounds/{round_id}/guess", json={"album_spotify_id": ALBUM_B})
    assert wrong_1.status_code == 200
    wrong_1_body = wrong_1.json()
    assert wrong_1_body["correct"] is False
    assert wrong_1_body["newly_revealed_metric"] is None
    assert wrong_1_body["eliminated_album_ids"] == [ALBUM_B]
    for name in SECRET_TRACK_NAMES:
        assert name not in json.dumps(wrong_1_body)

    # wrong guess #2 crosses the first hint threshold (danceability), still no leakage,
    # and both wrong guesses so far remain eliminated (regression a prior bug only
    # reported the most recently guessed album)
    wrong_2 = client.post(f"/api/game/rounds/{round_id}/guess", json={"album_spotify_id": ALBUM_C})
    assert wrong_2.status_code == 200
    wrong_2_body = wrong_2.json()
    assert wrong_2_body["wrong_guess_count"] == 2
    assert set(wrong_2_body["eliminated_album_ids"]) == {ALBUM_B, ALBUM_C}
    assert wrong_2_body["newly_revealed_metric"]["metric"] == "danceability"
    raw_wrong_2 = json.dumps(wrong_2_body)
    for name in SECRET_TRACK_NAMES:
        assert name not in raw_wrong_2
    assert TARGET_ALBUM_NAME not in raw_wrong_2

    # reveal is refused before the round is solved
    early_reveal = client.post(f"/api/game/rounds/{round_id}/reveal")
    assert early_reveal.status_code == 409

    # correct guess ends the round without leaking track names itself
    correct = client.post(
        f"/api/game/rounds/{round_id}/guess", json={"album_spotify_id": ALBUM_TARGET}
    )
    assert correct.status_code == 200
    correct_body = correct.json()
    assert correct_body["correct"] is True
    for name in SECRET_TRACK_NAMES:
        assert name not in json.dumps(correct_body)

    # only now may the reveal step return the target's identity and track names
    reveal = client.post(f"/api/game/rounds/{round_id}/reveal")
    assert reveal.status_code == 200
    reveal_body = reveal.json()
    assert reveal_body["album_name"] == TARGET_ALBUM_NAME
    # only "danceability" was unlocked during play (wrong guess #2), but the
    # reveal screen must show every metric regardless of what was unlocked
    assert reveal_body["revealed_metrics"] == [
        "danceability",
        "acousticness",
        "instrumentalness",
        "speechiness",
        "loudness",
        "key",
    ]
    names_in_reveal = {track["name"] for track in reveal_body["tracks"]}
    assert names_in_reveal == set(SECRET_TRACK_NAMES)
    for track in reveal_body["tracks"]:
        assert track["danceability"] == 0.7
        assert track["acousticness"] == 0.2
        assert track["instrumentalness"] == 0.1
        assert track["speechiness"] == 0.05
        assert track["loudness"] == -6.0
        assert track["key"] == 3
        assert track["mode"] == 1


@respx.mock
@patch("app.game_service.random.shuffle", lambda seq: None)
def test_give_up_with_no_wrong_guesses_still_reveals_all_metrics(client):
    _setup(respx)

    start_response = client.post("/api/game/rounds", json={"artist_name": "Test Artist"})
    assert start_response.status_code == 200
    round_id = start_response.json()["round_id"]

    give_up = client.post(f"/api/game/rounds/{round_id}/reveal", params={"give_up": True})
    assert give_up.status_code == 200
    give_up_body = give_up.json()
    assert give_up_body["revealed_metrics"] == [
        "danceability",
        "acousticness",
        "instrumentalness",
        "speechiness",
        "loudness",
        "key",
    ]
    for track in give_up_body["tracks"]:
        assert track["danceability"] == 0.7
        assert track["key"] == 3
        assert track["mode"] == 1


@respx.mock
def test_start_round_for_artist_with_too_few_albums_returns_422(client):
    _mock_token(respx)
    _mock_search(respx)
    respx.get(url__regex=rf"https://api\.spotify\.com/v1/artists/{ARTIST_ID}/albums.*").mock(
        return_value=Response(
            200,
            json={
                "items": [
                    {"id": "only-one", "name": "Only Album", "album_type": "album", "images": []},
                ]
            },
        )
    )
    _mock_album_tracks(respx, "only-one", [{"id": "t1", "name": "Song One"}])

    response = client.post("/api/game/rounds", json={"artist_name": "Test Artist"})

    assert response.status_code == 422
    assert "enough" in response.json()["detail"].lower()


@respx.mock
def test_start_round_for_unknown_artist_returns_404(client):
    _mock_token(respx)
    respx.get(url__regex=r"https://api\.spotify\.com/v1/search\?.*").mock(
        return_value=Response(200, json={"artists": {"items": []}})
    )

    response = client.post("/api/game/rounds", json={"artist_name": "Nobody At All"})

    assert response.status_code == 404


@respx.mock
@patch("app.game_service.random.shuffle", lambda seq: None)
def test_start_round_filters_out_non_studio_editions(client):
    _mock_token(respx)
    _mock_search(respx)
    respx.get(url__regex=rf"https://api\.spotify\.com/v1/artists/{ARTIST_ID}/albums.*").mock(
        return_value=Response(
            200,
            json={
                "items": [
                    {
                        "id": "ram-anniv",
                        "name": "Random Access Memories (10th Anniversary Edition)",
                        "album_type": "album",
                        "images": [],
                    },
                    {"id": "homework", "name": "Homework", "album_type": "album", "images": []},
                    {
                        "id": "ram",
                        "name": "Random Access Memories",
                        "album_type": "album",
                        "images": [],
                    },
                    {"id": "discovery", "name": "Discovery", "album_type": "album", "images": []},
                    {
                        "id": "alive-2007",
                        "name": "Alive 2007",
                        "album_type": "album",
                        "images": [],
                    },
                ]
            },
        )
    )
    for album_id in ("homework", "ram", "discovery"):
        _mock_album_tracks(respx, album_id, [{"id": f"{album_id}-t1", "name": "Track"}])
    _mock_reccobeats_any(respx)

    response = client.post("/api/game/rounds", json={"artist_name": "Test Artist"})

    assert response.status_code == 200
    option_names = {option["name"] for option in response.json()["album_options"]}
    assert option_names == {"Homework", "Random Access Memories", "Discovery"}


@respx.mock
def test_search_artists_endpoint_returns_name_and_image(client):
    _mock_token(respx)
    respx.get(url__regex=r"https://api\.spotify\.com/v1/search\?.*").mock(
        return_value=Response(
            200,
            json={
                "artists": {
                    "items": [
                        {
                            "id": "kanye-id",
                            "name": "Kanye West",
                            "images": [{"url": "https://example.com/kanye.jpg"}],
                        }
                    ]
                }
            },
        )
    )

    response = client.get("/api/game/artists", params={"q": "kan"})

    assert response.status_code == 200
    assert response.json() == [
        {"spotify_id": "kanye-id", "name": "Kanye West", "image_url": "https://example.com/kanye.jpg"}
    ]


@respx.mock
@patch("app.game_service.random.shuffle", lambda seq: None)
def test_start_round_accepts_artist_spotify_id(client):
    _mock_token(respx)
    respx.get(f"https://api.spotify.com/v1/artists/{ARTIST_ID}").mock(
        return_value=Response(200, json={"id": ARTIST_ID, "name": "Test Artist"})
    )
    _mock_albums(respx)
    for album_id, tracks in (
        (ALBUM_TARGET, [{"id": "t1", "name": "Track"}]),
        (ALBUM_B, [{"id": "b1", "name": "B Track"}]),
        (ALBUM_C, [{"id": "c1", "name": "C Track"}]),
    ):
        _mock_album_tracks(respx, album_id, tracks)
    _mock_reccobeats_any(respx)

    response = client.post("/api/game/rounds", json={"artist_spotify_id": ARTIST_ID})

    assert response.status_code == 200
    assert response.json()["artist_name"] == "Test Artist"

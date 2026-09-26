from fake_upstream import ALBUMS

ALL_TABS = [
    "Energy level",
    "Danceability",
    "Acousticness",
    "Instrumentalness",
    "Speechiness",
    "Loudness",
    "Key",
]


def tracks_of(album_name):
    return next(tracks for name, tracks in ALBUMS.values() if name == album_name)


def start_round(landing_page):
    landing_page.type_artist("Fake Band")
    return landing_page.choose_suggestion("Fake Band")


def test_a_correct_guess_reveals_the_album_and_its_tracks(landing_page, target_album):
    round_page = start_round(landing_page)
    target = target_album()

    reveal = round_page.guess_correct(target)

    assert reveal.album_name() == target
    assert reveal.track_names() == tracks_of(target)
    assert reveal.metric_tabs() == ALL_TABS


def test_giving_up_reveals_the_answer(landing_page, target_album):
    round_page = start_round(landing_page)
    target = target_album()

    reveal = round_page.give_up()

    assert reveal.album_name() == target
    assert reveal.track_names() == tracks_of(target)
    assert reveal.metric_tabs() == ALL_TABS

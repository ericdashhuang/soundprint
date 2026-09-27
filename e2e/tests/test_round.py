import pytest

from fake_upstream import ALBUMS

ALBUM_NAMES = sorted(name for name, _tracks in ALBUMS.values())
ALL_TABS_LOCKED_EXCEPT_ENERGY = ["Energy level"]


@pytest.fixture
def round_page(landing_page):
    landing_page.type_artist("Fake Band")
    return landing_page.choose_suggestion("Fake Band")


def wrong_albums(round_page, target_album, count):
    """pick `count` album options that are not the secret target"""
    target = target_album()
    return [name for name in round_page.album_options() if name != target][:count]


@pytest.mark.smoke
def test_choosing_an_artist_starts_a_round(round_page):
    assert round_page.heading() == "Guess the Fake Band album"
    assert sorted(round_page.album_options()) == ALBUM_NAMES
    assert round_page.chart_is_displayed()
    assert round_page.metric_tabs() == ["Energy level"]

    glossary = round_page.glossary()
    assert len(glossary) == 7
    assert glossary["Energy level"] is False
    assert all(locked for term, locked in glossary.items() if term != "Energy level")


def test_a_wrong_guess_eliminates_that_album(round_page, target_album):
    [wrong] = wrong_albums(round_page, target_album, 1)

    round_page.guess_wrong(wrong)

    assert wrong not in round_page.album_options()
    assert len(round_page.album_options()) == len(ALBUM_NAMES) - 1
    assert round_page.wrong_guess_line().endswith("1 wrong guess")
    assert round_page.metric_tabs() == ["Energy level"]


def test_a_second_wrong_guess_unlocks_a_metric_and_keeps_eliminations(round_page, target_album):
    first, second = wrong_albums(round_page, target_album, 2)

    round_page.guess_wrong(first)
    round_page.guess_wrong(second)

    remaining = round_page.album_options()
    assert first not in remaining
    assert second not in remaining
    assert round_page.wrong_guess_line().endswith("2 wrong guesses")
    round_page.wait_for_metric_tabs(["Energy level", "Danceability"])
    assert round_page.glossary()["Danceability"] is False

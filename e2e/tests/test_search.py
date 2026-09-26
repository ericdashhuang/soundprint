import pytest


@pytest.mark.smoke
def test_typing_an_artist_name_shows_suggestions(landing_page):
    landing_page.type_artist("fake")

    assert landing_page.suggestion_names() == ["Fake Band", "Fake Orchestra"]


def test_unknown_artist_shows_an_error(landing_page):
    landing_page.type_artist("Nobody Here")
    landing_page.submit()

    assert 'Couldn\'t find an artist named "Nobody Here"' in landing_page.error_text()

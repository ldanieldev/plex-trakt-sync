import pytest

from plextrakt.matching.guid import ParsedGuid, external_ids, parse_guid


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("imdb://tt5433138", ParsedGuid("imdb", "tt5433138")),
        ("tmdb://385128", ParsedGuid("tmdb", "385128")),
        ("tvdb://8856", ParsedGuid("tvdb", "8856")),
        ("plex://movie/5d776b59ad5437001f79c6f8", ParsedGuid("plex", "5d776b59ad5437001f79c6f8")),
        ("local://3149", ParsedGuid("local", "3149")),
        (
            "com.plexapp.agents.imdb://tt0054215?lang=en",
            ParsedGuid("imdb", "tt0054215"),
        ),
        (
            "com.plexapp.agents.themoviedb://603?lang=en",
            ParsedGuid("tmdb", "603"),
        ),
        (
            "com.plexapp.agents.thetvdb://81189/3/7?lang=en",
            ParsedGuid("tvdb", "81189", season=3, episode=7),
        ),
        (
            "com.plexapp.agents.xbmcnfotv://100/1/2?lang=xn",
            ParsedGuid("tvdb", "100", season=1, episode=2),
        ),
    ],
)
def test_parse_guid(raw, expected):
    assert parse_guid(raw) == expected


def test_parse_guid_garbage_returns_none():
    assert parse_guid("not a guid") is None
    assert parse_guid("") is None


def test_external_ids_filters_and_casts():
    guids = [
        parse_guid("imdb://tt5433138"),
        parse_guid("tmdb://385128"),
        parse_guid("tvdb://8856"),
        parse_guid("plex://movie/abc"),
        parse_guid("local://1"),
    ]
    assert external_ids(guids) == {"imdb": "tt5433138", "tmdb": 385128, "tvdb": 8856}

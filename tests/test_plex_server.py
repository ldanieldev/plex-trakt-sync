from conftest import (
    FakeEpisode,
    FakeGuidTag,
    FakeMovie,
    FakePlexServer,
    FakeSection,
    FakeSession,
    FakeShow,
    FakeUser,
    dt,
)

from plextrakt.plex.server import PlexLibrary


def make_movie(watched=True):
    return FakeMovie(
        ratingKey=1,
        title="Heat",
        guid="plex://movie/abc",
        guids=[FakeGuidTag("imdb://tt0113277"), FakeGuidTag("tmdb://949")],
        viewCount=1 if watched else 0,
        lastViewedAt=dt(1_700_000_000) if watched else None,
    )


def make_show_with_episode():
    show = FakeShow(11, "plex://show/s1", [FakeGuidTag("tmdb://1429")])
    ep = FakeEpisode(
        ratingKey=101,
        title="E1",
        guid="plex://episode/e1",
        guids=[FakeGuidTag("tvdb://100")],
        grandparentRatingKey=11,
        grandparentGuid="plex://show/s1",
        parentIndex=1,
        index=1,
    )
    return show, ep


def test_scan_movies():
    server = FakePlexServer(sections=[FakeSection("movie", movies=[make_movie()])])
    items = list(PlexLibrary(server).scan())
    assert len(items) == 1
    item = items[0]
    assert item.media_type == "movie"
    assert item.watched is True
    assert item.last_viewed_at == 1_700_000_000
    assert {g.provider for g in item.guids} == {"imdb", "tmdb"}


def test_scan_episodes_attach_show_guids():
    show, ep = make_show_with_episode()
    server = FakePlexServer(sections=[FakeSection("show", shows=[show], episodes=[ep])])
    items = list(PlexLibrary(server).scan())
    assert len(items) == 1
    item = items[0]
    assert item.media_type == "episode"
    assert (item.season, item.number) == (1, 1)
    assert item.show_guid == "plex://show/s1"
    assert item.show_guids[0].provider == "tmdb"


def test_mark_watched():
    movie = make_movie(watched=False)
    server = FakePlexServer(sections=[FakeSection("movie", movies=[movie])], items=[movie])
    PlexLibrary(server).mark_watched(1)
    assert movie.marked is True


def test_owner_session_filters_non_owner():
    movie = make_movie()
    server = FakePlexServer(
        items=[movie],
        sessions=[FakeSession(sessionKey=7, ratingKey=1, user=FakeUser(id=33))],
    )
    assert PlexLibrary(server).owner_session(7) is None


def test_owner_session_returns_item():
    movie = make_movie()
    server = FakePlexServer(
        items=[movie],
        sessions=[FakeSession(sessionKey=7, ratingKey=1, user=FakeUser(id=1))],
    )
    item = PlexLibrary(server).owner_session(7)
    assert item.rating_key == 1
    assert item.duration_ms == 6_000_000


def test_owner_session_unknown_key():
    server = FakePlexServer()
    assert PlexLibrary(server).owner_session(99) is None


def test_legacy_movie_guid_fallback():
    m = FakeMovie(
        ratingKey=2,
        title="Psycho",
        guid="com.plexapp.agents.imdb://tt0054215?lang=en",
        guids=[],
        viewCount=1,
        lastViewedAt=dt(1_700_000_000),
    )
    server = FakePlexServer(sections=[FakeSection("movie", movies=[m])])
    item = next(iter(PlexLibrary(server).scan()))
    assert item.guids[0].provider == "imdb"
    assert item.guids[0].id == "tt0054215"


def test_legacy_episode_show_attribution_and_empty_own_ids():
    show = FakeShow(11, "com.plexapp.agents.thetvdb://81189?lang=en", [])
    ep = FakeEpisode(
        ratingKey=101,
        title="E1",
        guid="com.plexapp.agents.thetvdb://81189/3/7?lang=en",
        guids=[],
        grandparentRatingKey=11,
        grandparentGuid="com.plexapp.agents.thetvdb://81189?lang=en",
        parentIndex=3,
        index=7,
    )
    server = FakePlexServer(sections=[FakeSection("show", shows=[show], episodes=[ep])])
    item = next(iter(PlexLibrary(server).scan()))
    assert item.guids == ()  # legacy episode: no own external ids -> positional matching
    assert item.show_guids[0].provider == "tvdb"
    assert item.show_guids[0].id == "81189"
    assert (item.season, item.number) == (3, 7)


def test_scan_skips_excluded_sections():
    included = FakeSection("movie", movies=[make_movie()], title="Movies")
    excluded = FakeSection("movie", movies=[make_movie()], title="Other Videos")
    server = FakePlexServer(sections=[included, excluded])
    lib = PlexLibrary(server, exclude_libraries=frozenset({"other videos"}))
    assert len(list(lib.scan())) == 1

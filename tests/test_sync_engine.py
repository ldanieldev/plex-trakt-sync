from plextrakt.matching.guid import parse_guid
from plextrakt.matching.resolver import Resolver
from plextrakt.plex.server import PlexItem
from plextrakt.state.db import StateDB
from plextrakt.sync.engine import SyncEngine


def movie(rk, title, watched, guids=("imdb://tt1", "tmdb://5"), guid="plex://movie/m"):
    return PlexItem(
        rating_key=rk,
        media_type="movie",
        title=title,
        guid=guid,
        guids=tuple(parse_guid(g) for g in guids),
        watched=watched,
        last_viewed_at=1_700_000_000 if watched else None,
        duration_ms=6_000_000,
    )


def episode(rk, title, watched, season, number, ep_guids=("tvdb://100",)):
    return PlexItem(
        rating_key=rk,
        media_type="episode",
        title=title,
        guid=f"plex://episode/{rk}",
        guids=tuple(parse_guid(g) for g in ep_guids),
        watched=watched,
        last_viewed_at=1_700_000_000 if watched else None,
        duration_ms=1_500_000,
        show_guid="plex://show/s1",
        show_guids=(parse_guid("tmdb://1429"),),
        season=season,
        number=number,
    )


class FakePlex:
    def __init__(self, items):
        self.items = items
        self.marked: list[int] = []

    def scan(self):
        yield from self.items

    def mark_watched(self, rating_key):
        self.marked.append(rating_key)


class FakeTrakt:
    def __init__(self, watched_movie_ids=(), watched_eps=()):
        # watched_movie_ids: iterable of imdb ids; watched_eps: {(season, number)}
        self._movies = [
            {
                "plays": 1,
                "last_watched_at": "2026-01-01T00:00:00.000Z",
                "movie": {
                    "title": "w",
                    "ids": {"trakt": 900, "imdb": i, "plex": {"guid": "abc123", "slug": "x"}},
                },
            }
            for i in watched_movie_ids
        ]
        self._shows = (
            [
                {
                    "show": {"ids": {"trakt": 1420, "tmdb": 1429}},
                    "seasons": [
                        {"number": s, "episodes": [{"number": n, "plays": 1}]}
                        for (s, n) in watched_eps
                    ],
                }
            ]
            if watched_eps
            else []
        )
        self.history_posts: list[dict] = []
        self.not_found: dict = {"movies": [], "shows": [], "seasons": [], "episodes": []}
        self.lookup_error = False

    def watched_movies(self):
        return self._movies

    def watched_shows(self):
        return self._shows

    def add_history(self, movies=(), episodes=()):
        self.history_posts.append({"movies": list(movies), "episodes": list(episodes)})
        return {
            "added": {"movies": len(movies), "episodes": len(episodes)},
            "not_found": self.not_found,
        }

    def lookup_id(self, id_type, id_value, media_type):
        if self.lookup_error:
            raise RuntimeError("boom")
        if (id_type, id_value) == ("tmdb", 1429):
            return {"ids": {"trakt": 1420, "tmdb": 1429}}
        return None

    def episode_table(self, show_trakt_id):
        return [
            {"season": 1, "number": 1, "ids": {"trakt": 10, "tvdb": 100}},
            {"season": 1, "number": 2, "ids": {"trakt": 11, "tvdb": 101}},
        ]


def make_engine(tmp_path, plex, trakt):
    db = StateDB(tmp_path / "s.db")
    return SyncEngine(plex, trakt, Resolver(trakt, db, now=lambda: 1000.0), db, now=lambda: 1000.0)


def test_plex_watched_movie_pushed_to_trakt(tmp_path):
    plex = FakePlex([movie(1, "Heat", watched=True)])
    trakt = FakeTrakt()
    report = make_engine(tmp_path, plex, trakt).run()
    assert report.to_trakt == 1
    posted = trakt.history_posts[0]["movies"][0]
    assert posted["ids"]["imdb"] == "tt1"
    assert posted["watched_at"] == "2023-11-14T22:13:20Z"  # epoch 1700000000 as UTC ISO
    assert plex.marked == []


def test_trakt_watched_movie_marked_in_plex(tmp_path):
    plex = FakePlex([movie(1, "Heat", watched=False, guids=("imdb://tt1",))])
    trakt = FakeTrakt(watched_movie_ids=["tt1"])
    report = make_engine(tmp_path, plex, trakt).run()
    assert report.to_plex == 1
    assert plex.marked == [1]
    assert trakt.history_posts == []


def test_already_synced_movie_is_noop(tmp_path):
    plex = FakePlex([movie(1, "Heat", watched=True, guids=("imdb://tt1",))])
    trakt = FakeTrakt(watched_movie_ids=["tt1"])
    report = make_engine(tmp_path, plex, trakt).run()
    assert report.to_trakt == 0 and report.to_plex == 0
    assert trakt.history_posts == []


def test_local_movie_skipped(tmp_path):
    plex = FakePlex([movie(1, "Home Video", watched=True, guids=("local://1",), guid="local://1")])
    trakt = FakeTrakt()
    report = make_engine(tmp_path, plex, trakt).run()
    assert report.skipped["unmatched-in-plex"] == ["Home Video"]
    assert trakt.history_posts == []


def test_watched_episode_pushed_by_trakt_id(tmp_path):
    plex = FakePlex([episode(101, "E1", watched=True, season=1, number=1)])
    trakt = FakeTrakt()
    report = make_engine(tmp_path, plex, trakt).run()
    assert report.to_trakt == 1
    posted = trakt.history_posts[0]["episodes"][0]
    assert posted["ids"]["trakt"] == 10


def test_poisoned_item_does_not_abort_run(tmp_path):
    good = movie(1, "Heat", watched=True)
    bad = episode(102, "Cursed", watched=True, season=1, number=1)
    plex = FakePlex([bad, good])
    trakt = FakeTrakt()
    trakt.lookup_error = True  # show resolution for the episode explodes
    report = make_engine(tmp_path, plex, trakt).run()
    assert report.errors == 1
    assert report.to_trakt == 1  # the movie still synced


def test_not_found_lands_in_report(tmp_path):
    plex = FakePlex([movie(1, "Obscure", watched=True, guids=("imdb://tt9",))])
    trakt = FakeTrakt()
    trakt.not_found = {
        "movies": [{"ids": {"imdb": "tt9"}}],
        "shows": [],
        "seasons": [],
        "episodes": [],
    }
    report = make_engine(tmp_path, plex, trakt).run()
    assert report.skipped["not-found-on-trakt"] == ["Obscure"]
    assert report.to_trakt == 0


def test_scrobbled_item_not_repushed(tmp_path):
    plex = FakePlex([episode(101, "E1", watched=True, season=1, number=1)])
    trakt = FakeTrakt()
    db = StateDB(tmp_path / "s.db")
    db.record_scrobble("episode", 10, at=999)  # trakt id 10 = S1E1 in FakeTrakt's table
    engine = SyncEngine(
        plex, trakt, Resolver(trakt, db, now=lambda: 1000.0), db, now=lambda: 1000.0
    )
    report = engine.run()
    assert trakt.history_posts == []
    assert report.to_trakt == 0


def test_scrobbled_movie_not_repushed_by_external_id(tmp_path):
    plex = FakePlex([movie(1, "Heat", watched=True, guids=("imdb://tt1",))])
    trakt = FakeTrakt()  # not in trakt watched response yet
    db = StateDB(tmp_path / "s.db")
    db.record_scrobble("movie", "tt1", at=999)
    engine = SyncEngine(
        plex, trakt, Resolver(trakt, db, now=lambda: 1000.0), db, now=lambda: 1000.0
    )
    report = engine.run()
    assert trakt.history_posts == []
    assert report.to_trakt == 0


def test_not_found_matches_multikey_ids(tmp_path):
    plex = FakePlex([movie(1, "Obscure", watched=True, guids=("imdb://tt9", "tmdb://77"))])
    trakt = FakeTrakt()
    trakt.not_found = {
        "movies": [{"ids": {"imdb": "tt9", "tmdb": 77}}],  # full echo of what was sent
        "shows": [],
        "seasons": [],
        "episodes": [],
    }
    report = make_engine(tmp_path, plex, trakt).run()
    assert report.skipped["not-found-on-trakt"] == ["Obscure"]
    assert report.to_trakt == 0

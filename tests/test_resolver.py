from plextrakt.matching.guid import parse_guid
from plextrakt.matching.resolver import (
    EPISODE_MISSING,
    MATCHED,
    SHOW_MISSING,
    UNMATCHED_IN_PLEX,
    Resolver,
)
from plextrakt.state.db import StateDB


class FakeTrakt:
    def __init__(self):
        self.shows = {("tmdb", 1429): {"ids": {"trakt": 1420, "tmdb": 1429, "tvdb": 267440}}}
        self.tables = {
            1420: [
                {"season": 1, "number": 1, "ids": {"trakt": 10, "tvdb": 100, "tmdb": 900}},
                {"season": 1, "number": 2, "ids": {"trakt": 11, "tvdb": 101, "tmdb": 901}},
                {"season": 2, "number": 1, "ids": {"trakt": 20, "tvdb": 300, "tmdb": 902}},
            ]
        }
        self.table_calls = 0
        self.lookup_calls = 0

    def lookup_id(self, id_type, id_value, media_type):
        self.lookup_calls += 1
        entry = self.shows.get((id_type, id_value))
        return dict(entry) if entry else None

    def episode_table(self, show_trakt_id):
        self.table_calls += 1
        return list(self.tables.get(show_trakt_id, []))


def make_resolver(tmp_path):
    trakt = FakeTrakt()
    db = StateDB(tmp_path / "s.db")
    return Resolver(trakt, db, now=lambda: 1000.0), trakt


SHOW_GUIDS = [parse_guid("tmdb://1429"), parse_guid("tvdb://267440")]


def test_movie_with_external_ids_matches(tmp_path):
    r, _ = make_resolver(tmp_path)
    out = r.resolve_movie(1, "plex://movie/x", [parse_guid("imdb://tt1"), parse_guid("tmdb://5")])
    assert out.status == MATCHED
    assert out.ids.imdb == "tt1" and out.ids.tmdb == 5


def test_movie_local_guid_is_unmatched(tmp_path):
    r, _ = make_resolver(tmp_path)
    out = r.resolve_movie(2, "local://2", [parse_guid("local://2")])
    assert out.status == UNMATCHED_IN_PLEX


def test_show_resolution_and_memoization(tmp_path):
    r, trakt = make_resolver(tmp_path)
    out1 = r.resolve_show("plex://show/a", SHOW_GUIDS)
    out2 = r.resolve_show("plex://show/a", SHOW_GUIDS)
    assert out1.status == MATCHED and out1.ids.trakt == 1420
    assert out2 is out1  # memoized per run


def test_show_missing_on_trakt(tmp_path):
    r, _ = make_resolver(tmp_path)
    out = r.resolve_show("plex://show/b", [parse_guid("tmdb://999")])
    assert out.status == SHOW_MISSING


def test_show_match_persisted_across_runs(tmp_path):
    trakt = FakeTrakt()
    db = StateDB(tmp_path / "s.db")
    r1 = Resolver(trakt, db, now=lambda: 1000.0)
    r1.resolve_show("plex://show/a", SHOW_GUIDS)
    assert trakt.lookup_calls == 1
    # fresh Resolver (new run), same db -> served from the persisted match cache
    r2 = Resolver(trakt, db, now=lambda: 1000.0)
    out = r2.resolve_show("plex://show/a", SHOW_GUIDS)
    assert out.status == MATCHED and out.ids.trakt == 1420
    assert trakt.lookup_calls == 1


def test_episode_positional_match_validates(tmp_path):
    r, _ = make_resolver(tmp_path)
    show = r.resolve_show("plex://show/a", SHOW_GUIDS)
    out = r.resolve_episode(show, 1, 2, [parse_guid("tvdb://101")])
    assert out.status == MATCHED
    assert out.ids.trakt == 11
    assert out.ordering_fallback is False


def test_episode_ordering_divergence_uses_id_fallback(tmp_path):
    # Plex says S3E1 (TVDB-style split); Trakt has that episode as S2E1 (tvdb 300)
    r, _ = make_resolver(tmp_path)
    show = r.resolve_show("plex://show/a", SHOW_GUIDS)
    out = r.resolve_episode(show, 3, 1, [parse_guid("tvdb://300")])
    assert out.status == MATCHED
    assert out.ids.trakt == 20
    assert out.ordering_fallback is True
    assert (out.season, out.number) == (2, 1)  # Trakt-side coordinates


def test_episode_positional_hit_with_wrong_id_falls_back(tmp_path):
    # positional S1E1 exists but Plex's episode carries tvdb 300 (a different episode)
    r, _ = make_resolver(tmp_path)
    show = r.resolve_show("plex://show/a", SHOW_GUIDS)
    out = r.resolve_episode(show, 1, 1, [parse_guid("tvdb://300")])
    assert out.ids.trakt == 20
    assert out.ordering_fallback is True


def test_episode_missing_everywhere(tmp_path):
    r, _ = make_resolver(tmp_path)
    show = r.resolve_show("plex://show/a", SHOW_GUIDS)
    out = r.resolve_episode(show, 9, 9, [parse_guid("tvdb://777")])
    assert out.status == EPISODE_MISSING


def test_episode_without_ids_accepts_positional(tmp_path):
    r, _ = make_resolver(tmp_path)
    show = r.resolve_show("plex://show/a", SHOW_GUIDS)
    out = r.resolve_episode(show, 1, 1, [])
    assert out.status == MATCHED and out.ids.trakt == 10


def test_episode_table_cached_in_db(tmp_path):
    r, trakt = make_resolver(tmp_path)
    show = r.resolve_show("plex://show/a", SHOW_GUIDS)
    r.resolve_episode(show, 1, 1, [])
    r.resolve_episode(show, 1, 2, [])
    assert trakt.table_calls == 1

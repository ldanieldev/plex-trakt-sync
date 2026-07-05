from plextrakt.matching.guid import parse_guid
from plextrakt.plex.server import PlexItem
from plextrakt.scrobble.scrobbler import Scrobbler
from plextrakt.state.db import StateDB

MOVIE = PlexItem(
    rating_key=1,
    media_type="movie",
    title="Heat",
    guid="plex://movie/m",
    guids=(parse_guid("imdb://tt1"), parse_guid("tmdb://949")),
    watched=False,
    last_viewed_at=None,
    duration_ms=100_000,
)

EPISODE = PlexItem(
    rating_key=101,
    media_type="episode",
    title="E1",
    guid="plex://episode/e",
    guids=(parse_guid("tvdb://100"),),
    watched=False,
    last_viewed_at=None,
    duration_ms=100_000,
    show_guid="plex://show/s1",
    show_guids=(parse_guid("tmdb://1429"),),
    season=1,
    number=1,
)


class FakePlex:
    def __init__(self, item=MOVIE, owner=True):
        self.item = item
        self.owner = owner
        self.lookups = 0

    def owner_session(self, session_key):
        self.lookups += 1
        return self.item if self.owner else None


class FakeTrakt:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self.stop_response = {"action": "scrobble", "id": 999, "movie": {"ids": {"trakt": 5}}}

    def scrobble(self, action, payload):
        self.calls.append((action, payload))
        if action == "stop":
            return self.stop_response
        return {"action": action}

    def lookup_id(self, id_type, id_value, media_type):
        if (id_type, id_value) == ("tmdb", 1429):
            return {"ids": {"trakt": 1420, "tmdb": 1429}}
        return None

    def episode_table(self, show_trakt_id):
        return [{"season": 1, "number": 1, "ids": {"trakt": 10, "tvdb": 100}}]


def make(tmp_path, plex=None, trakt=None):
    from plextrakt.matching.resolver import Resolver

    trakt = trakt or FakeTrakt()
    db = StateDB(tmp_path / "s.db")
    resolver = Resolver(trakt, db, now=lambda: 1000.0)
    plex = plex or FakePlex()
    return Scrobbler(plex, trakt, resolver, db, now=lambda: 1000.0), plex, trakt, db


def notif(state, key="7", offset=10_000):
    return {"sessionKey": key, "state": state, "viewOffset": offset}


def test_start_pause_resume_stop_flow(tmp_path):
    s, _, trakt, db = make(tmp_path)
    s.handle_playing(notif("playing", offset=10_000))
    s.handle_playing(notif("playing", offset=20_000))  # same state -> no new call
    s.handle_playing(notif("paused", offset=30_000))
    s.handle_playing(notif("playing", offset=30_000))  # resume -> start again
    s.handle_playing(notif("stopped", offset=95_000))
    actions = [a for a, _ in trakt.calls]
    assert actions == ["start", "pause", "start", "stop"]
    assert trakt.calls[-1][1]["progress"] == 95.0
    assert trakt.calls[0][1]["movie"]["ids"]["imdb"] == "tt1"
    assert ("movie", 5) in db.scrobbled_ids()


def test_non_owner_ignored_with_single_lookup(tmp_path):
    s, plex, trakt, _ = make(tmp_path, plex=FakePlex(owner=False))
    s.handle_playing(notif("playing"))
    s.handle_playing(notif("playing"))
    assert trakt.calls == []
    assert plex.lookups == 1


def test_duplicate_stop_not_recorded(tmp_path):
    trakt = FakeTrakt()
    trakt.stop_response = {"action": "duplicate", "watched_at": "2026-01-01T00:00:00Z"}
    s, _, _, db = make(tmp_path, trakt=trakt)
    s.handle_playing(notif("playing"))
    s.handle_playing(notif("stopped", offset=95_000))
    assert db.scrobbled_ids() == set()


def test_episode_scrobbles_by_trakt_id(tmp_path):
    s, _, trakt, _ = make(tmp_path, plex=FakePlex(item=EPISODE))
    s.handle_playing(notif("playing"))
    action, payload = trakt.calls[0]
    assert payload["episode"]["ids"]["trakt"] == 10


def test_stop_for_unknown_session_is_ignored(tmp_path):
    s, plex, trakt, _ = make(tmp_path)
    s.handle_playing(notif("stopped"))
    assert trakt.calls == []
    assert plex.lookups == 0


def test_buffering_is_ignored(tmp_path):
    s, _, trakt, _ = make(tmp_path)
    s.handle_playing(notif("playing"))
    s.handle_playing(notif("buffering"))
    assert [a for a, _ in trakt.calls] == ["start"]

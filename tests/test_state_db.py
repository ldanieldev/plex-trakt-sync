from plextrakt.state.db import StateDB, TokenPair, TraktIds


def make_db(tmp_path):
    return StateDB(tmp_path / "state.db")


def test_token_roundtrip_and_rotation(tmp_path):
    db = make_db(tmp_path)
    assert db.load_tokens() is None
    db.save_tokens(TokenPair("a1", "r1", created_at=1000, expires_in=86400))
    db.save_tokens(TokenPair("a2", "r2", created_at=2000, expires_in=86400))
    pair = db.load_tokens()
    assert (pair.access_token, pair.refresh_token) == ("a2", "r2")
    assert pair.refresh_after == 2000 + int(0.8 * 86400)


def test_match_cache_roundtrip(tmp_path):
    db = make_db(tmp_path)
    ids = TraktIds(trakt=42, imdb="tt1", tmdb=7, tvdb=None)
    db.set_match("plex://show/abc", ids)
    assert db.get_match("plex://show/abc") == ids
    # a fix-match in Plex produces a NEW guid -> naturally a cache miss
    assert db.get_match("plex://show/DIFFERENT") is None


def test_episode_table_ttl(tmp_path):
    db = make_db(tmp_path)
    table = [{"season": 1, "number": 1, "ids": {"trakt": 9}}]
    db.set_episode_table(37696, table, now=1000)
    assert db.get_episode_table(37696, max_age_s=500, now=1400) == table
    assert db.get_episode_table(37696, max_age_s=500, now=1600) is None


def test_scrobble_dedup_set(tmp_path):
    db = make_db(tmp_path)
    db.record_scrobble("episode", 9, at=123)
    db.record_scrobble("episode", 9, at=456)  # idempotent
    db.record_scrobble("movie", 5, at=789)
    assert db.scrobbled_ids() == {("episode", 9), ("movie", 5)}


def test_creates_missing_parent_dirs(tmp_path):
    nested = tmp_path / "sub" / "dir" / "state.db"
    db = StateDB(nested)
    db.record_scrobble("movie", 1, at=1)
    assert nested.exists()

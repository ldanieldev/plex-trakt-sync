import json
import sqlite3
import threading
from dataclasses import asdict, dataclass
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tokens (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    access_token TEXT NOT NULL,
    refresh_token TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    expires_in INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS match_cache (
    plex_guid TEXT PRIMARY KEY,
    ids_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS episode_tables (
    show_trakt_id INTEGER PRIMARY KEY,
    table_json TEXT NOT NULL,
    fetched_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS scrobbled (
    trakt_type TEXT NOT NULL,
    trakt_id INTEGER NOT NULL,
    scrobbled_at INTEGER NOT NULL,
    PRIMARY KEY (trakt_type, trakt_id)
);
"""


@dataclass
class TokenPair:
    access_token: str
    refresh_token: str
    created_at: int
    expires_in: int

    @property
    def refresh_after(self) -> int:
        return self.created_at + int(0.8 * self.expires_in)


@dataclass(frozen=True)
class TraktIds:
    trakt: int | None = None
    imdb: str | None = None
    tmdb: int | None = None
    tvdb: int | None = None

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}

    @classmethod
    def from_dict(cls, data: dict) -> "TraktIds":
        return cls(**{k: data.get(k) for k in ("trakt", "imdb", "tmdb", "tvdb")})


class StateDB:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.Lock()
        self._conn.executescript(_SCHEMA)

    def save_tokens(self, pair: TokenPair) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO tokens (id, access_token, refresh_token,"
                " created_at, expires_in) VALUES (1, ?, ?, ?, ?)",
                (pair.access_token, pair.refresh_token, pair.created_at, pair.expires_in),
            )

    def load_tokens(self) -> TokenPair | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT access_token, refresh_token, created_at, expires_in FROM tokens"
            ).fetchone()
            return TokenPair(*row) if row else None

    def set_match(self, plex_guid: str, ids: TraktIds) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO match_cache VALUES (?, ?)",
                (plex_guid, json.dumps(ids.to_dict())),
            )

    def get_match(self, plex_guid: str) -> TraktIds | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT ids_json FROM match_cache WHERE plex_guid = ?", (plex_guid,)
            ).fetchone()
            return TraktIds.from_dict(json.loads(row[0])) if row else None

    def set_episode_table(self, show_trakt_id: int, table: list[dict], now: int) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO episode_tables VALUES (?, ?, ?)",
                (show_trakt_id, json.dumps(table), now),
            )

    def get_episode_table(self, show_trakt_id: int, max_age_s: int, now: int) -> list[dict] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT table_json, fetched_at FROM episode_tables WHERE show_trakt_id = ?",
                (show_trakt_id,),
            ).fetchone()
            if row is None or now - row[1] > max_age_s:
                return None
            return json.loads(row[0])

    def record_scrobble(self, trakt_type: str, trakt_id: int, at: int) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO scrobbled VALUES (?, ?, ?)",
                (trakt_type, trakt_id, at),
            )

    def scrobbled_ids(self) -> set[tuple[str, int]]:
        with self._lock:
            rows = self._conn.execute("SELECT trakt_type, trakt_id FROM scrobbled").fetchall()
            return {(t, i) for t, i in rows}

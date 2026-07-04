from pathlib import Path

import pytest
from pydantic_core import ValidationError

from plextrakt.config import Settings

REQUIRED = {
    "PLEX_URL": "http://plex:32400",
    "PLEX_TOKEN": "ptok",
    "TRAKT_CLIENT_ID": "cid",
    "TRAKT_CLIENT_SECRET": "csec",
}


def set_required(monkeypatch):
    for k, v in REQUIRED.items():
        monkeypatch.setenv(k, v)


def test_loads_from_env_with_defaults(monkeypatch):
    set_required(monkeypatch)
    s = Settings()
    assert s.plex_url == "http://plex:32400"
    assert s.trakt_client_secret == "csec"
    assert s.sync_interval == "6h"
    assert s.metrics_port == 9308
    assert s.state_dir == Path("/config")


@pytest.mark.parametrize(
    "raw,seconds",
    [("6h", 21600), ("90m", 5400), ("45s", 45), ("1d", 86400), ("300", 300)],
)
def test_sync_interval_seconds(monkeypatch, raw, seconds):
    set_required(monkeypatch)
    monkeypatch.setenv("SYNC_INTERVAL", raw)
    assert Settings().sync_interval_seconds == seconds


def test_missing_required_raises(monkeypatch):
    for k in REQUIRED:
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(ValidationError):
        Settings()

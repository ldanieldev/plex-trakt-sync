from pathlib import Path

from pydantic_settings import BaseSettings

_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


class Settings(BaseSettings):
    plex_url: str
    plex_token: str
    trakt_client_id: str
    trakt_client_secret: str
    sync_interval: str = "6h"
    metrics_port: int = 9308
    log_level: str = "INFO"
    log_format: str = "json"
    state_dir: Path = Path("/config")

    @property
    def sync_interval_seconds(self) -> int:
        raw = self.sync_interval.strip().lower()
        if raw and raw[-1] in _UNITS:
            return int(float(raw[:-1]) * _UNITS[raw[-1]])
        return int(raw)

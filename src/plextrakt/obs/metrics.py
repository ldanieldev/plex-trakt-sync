from prometheus_client import Counter, Gauge, start_http_server

SYNC_RUNS = Counter("plextrakt_sync_runs_total", "Sync runs by result", ["result"])
SYNC_ITEMS = Counter(
    "plextrakt_sync_items_total", "Items handled during sync", ["direction", "outcome"]
)
SCROBBLES = Counter("plextrakt_scrobbles_total", "Scrobble calls by action", ["action"])
LISTENER_RESTARTS = Counter("plextrakt_listener_restarts_total", "Plex websocket listener restarts")
TRAKT_REQUESTS = Counter(
    "plextrakt_trakt_requests_total", "Trakt HTTP responses by status", ["status"]
)
TRAKT_RATE_LIMITED = Counter("plextrakt_trakt_rate_limited_total", "Trakt 429 responses")
LAST_SYNC_SUCCESS = Gauge(
    "plextrakt_sync_last_success_timestamp", "Unix time of last successful sync"
)


def start_metrics_server(port: int) -> None:
    start_http_server(port)

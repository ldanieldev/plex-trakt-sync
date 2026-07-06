# plextrakt

Single-user Plex ↔ Trakt watched-status sync and scrobbler. Keeps your Plex and Trakt libraries in sync and automatically scrobbles playback to Trakt.

## Quick Start

1. **Register a Trakt app** at https://trakt.tv/oauth/applications with:
   - Redirect URI: `urn:ietf:wg:oauth:2.0:oob` (device flow)
   - Note your Client ID and Client Secret

2. **Authorize and test** (one-time):
   ```bash
   docker run -it --rm -v /path/to/config:/config \
     -e PLEX_URL=http://plex:32400 \
     -e PLEX_TOKEN=xxx \
     -e TRAKT_CLIENT_ID=xxx \
     -e TRAKT_CLIENT_SECRET=xxx \
     ghcr.io/ldanieldev/plex-trakt-sync:latest login
   ```
   Follow the Trakt device flow link, then verify Plex connection.

3. **Run as daemon** (docker-compose or direct):
   ```bash
   docker run -d --restart unless-stopped \
     -v /path/to/config:/config \
     -p 9308:9308 \
     -e PLEX_URL=http://plex:32400 \
     -e PLEX_TOKEN=xxx \
     -e TRAKT_CLIENT_ID=xxx \
     -e TRAKT_CLIENT_SECRET=xxx \
     ghcr.io/ldanieldev/plex-trakt-sync:latest run
   ```

## Commands

| Command | Purpose |
|---------|---------|
| `login` | Authorize with Trakt (device flow) and verify Plex connection. |
| `sync` | One-time two-way watched-status sync. |
| `watch` | Live scrobbler until interrupted. |
| `run` | Default container mode: scrobbler + periodic sync + metrics. |

## Environment Variables

| Variable | Default | Required | Notes |
|----------|---------|----------|-------|
| `PLEX_URL` | — | Yes | Full URL, e.g. `http://192.168.1.x:32400` |
| `PLEX_TOKEN` | — | Yes | Plex API token |
| `PLEX_EXCLUDE_LIBRARIES` | (empty) | No | Comma-separated Plex library names to skip during sync (case-insensitive) |
| `TRAKT_CLIENT_ID` | — | Yes | From your registered Trakt app |
| `TRAKT_CLIENT_SECRET` | — | Yes | From your registered Trakt app |
| `SYNC_INTERVAL` | `6h` | No | Sync frequency: `30m`, `2h`, `1d`, etc. |
| `METRICS_PORT` | `9308` | No | Prometheus metrics; set to `0` to disable |
| `LOG_LEVEL` | `INFO` | No | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `LOG_FORMAT` | `json` | No | `json` or `text` |
| `STATE_DIR` | `/config` | No | Persistent state directory (don't change in container) |

## Metrics

Prometheus metrics at `http://localhost:9308/metrics`:
- `plextrakt_sync_runs_total` — Sync runs by result
- `plextrakt_sync_items_total` — Items processed by direction and outcome
- `plextrakt_scrobbles_total` — Scrobble calls by action
- `plextrakt_listener_restarts_total` — Plex listener restarts
- `plextrakt_trakt_requests_total` — Trakt HTTP responses by status
- `plextrakt_trakt_rate_limited_total` — Trakt 429 rate-limit hits
- `plextrakt_sync_last_success_timestamp` — Unix timestamp of last successful sync

## Matching Notes

When an item cannot be matched to Trakt, it is skipped with a category:
- **unmatched-in-plex**: No external IDs (TMDB, TVDB, IMDb) found in Plex
- **show-missing-on-trakt**: Show has IDs but not found on Trakt
- **episode-missing-on-trakt**: Episode not found on Trakt
- **not-found-on-trakt**: Sync push rejected by Trakt
- **ordering-mismatch-resolved**: Episode matched by ID despite season/episode number mismatch

### Anime Ordering

Plex and Trakt may use different episode numbering for anime. **For anime libraries, set episode ordering in Plex to "TheMovieDB (Aired)"** to minimize mismatches. If an episode is correctly matched by external ID but has a different number in Plex, it will be synced and noted as `ordering-mismatch-resolved`.

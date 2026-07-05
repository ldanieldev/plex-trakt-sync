import threading
import time
from dataclasses import dataclass, field
from functools import cached_property

import httpx
import structlog
import typer

from plextrakt.config import Settings
from plextrakt.obs.logging import configure_logging
from plextrakt.obs.metrics import start_metrics_server

app = typer.Typer(help="Single-user Plex <-> Trakt watched-status sync and scrobbler.")
log = structlog.get_logger()


@dataclass
class AppContext:
    settings: Settings = field(default_factory=Settings)

    @cached_property
    def db(self):
        from plextrakt.state.db import StateDB

        return StateDB(self.settings.state_dir / "state.db")

    @cached_property
    def auth(self):
        from plextrakt.trakt.auth import TraktAuth

        return TraktAuth(
            self.settings.trakt_client_id,
            self.settings.trakt_client_secret,
            self.db,
            httpx.Client(timeout=30),
        )

    @cached_property
    def trakt(self):
        from plextrakt.trakt.client import TraktClient
        from plextrakt.trakt.ratelimit import WriteRateLimiter

        return TraktClient(self.auth, WriteRateLimiter(), httpx.Client(timeout=30))

    @cached_property
    def resolver(self):
        from plextrakt.matching.resolver import Resolver

        return Resolver(self.trakt, self.db)

    @cached_property
    def plex(self):
        from plexapi.server import PlexServer

        from plextrakt.plex.server import PlexLibrary

        return PlexLibrary(PlexServer(self.settings.plex_url, self.settings.plex_token))

    def engine(self):
        from plextrakt.matching.resolver import Resolver
        from plextrakt.sync.engine import SyncEngine

        return SyncEngine(self.plex, self.trakt, Resolver(self.trakt, self.db), self.db)

    def scrobbler(self):
        from plextrakt.scrobble.scrobbler import Scrobbler

        return Scrobbler(self.plex, self.trakt, self.resolver, self.db)


def build_context() -> AppContext:
    return AppContext()


def _setup(ctx: AppContext) -> None:
    configure_logging(ctx.settings.log_level, ctx.settings.log_format)


@app.command()
def login():
    """Authorize this app with Trakt (device flow) and verify the Plex connection."""
    ctx = build_context()
    _setup(ctx)
    device = ctx.auth.request_device_code()
    typer.echo(f"Go to {device['verification_url']} and enter code: {device['user_code']}")
    ctx.auth.poll_device_token(device)
    typer.echo("Trakt: authorized.")
    server = ctx.plex._server  # force the connection
    typer.echo(f"Plex: connected to {server.friendlyName}.")


@app.command()
def sync():
    """Run one two-way watched-status sync."""
    ctx = build_context()
    _setup(ctx)
    try:
        report = ctx.engine().run()
    except Exception as exc:
        log.error("sync_fatal", error=str(exc))
        raise typer.Exit(code=1) from exc
    typer.echo(
        f"sync complete: to_trakt={report.to_trakt} to_plex={report.to_plex} "
        f"errors={report.errors} skipped={sum(len(v) for v in report.skipped.values())}"
    )
    for category, titles in report.skipped.items():
        for title in titles:
            typer.echo(f"  [{category}] {title}")


@app.command()
def watch():
    """Run the live scrobbler until interrupted."""
    ctx = build_context()
    _setup(ctx)
    if ctx.settings.metrics_port:
        start_metrics_server(ctx.settings.metrics_port)
    from plextrakt.plex.listener import SupervisedListener

    scrobbler = ctx.scrobbler()
    SupervisedListener(ctx.plex._server, scrobbler.handle_playing).run_forever()


@app.command()
def run():
    """Container default: scrobbler + periodic sync + metrics."""
    ctx = build_context()
    _setup(ctx)
    if ctx.settings.metrics_port:
        start_metrics_server(ctx.settings.metrics_port)
    from plextrakt.plex.listener import SupervisedListener

    scrobbler = ctx.scrobbler()
    listener = SupervisedListener(ctx.plex._server, scrobbler.handle_playing)
    threading.Thread(target=listener.run_forever, daemon=True, name="listener").start()
    interval = ctx.settings.sync_interval_seconds
    while True:
        try:
            ctx.engine().run()
        except Exception as exc:
            from plextrakt.obs import metrics as m

            m.SYNC_RUNS.labels(result="fatal").inc()
            log.error("sync_fatal", error=str(exc))
        time.sleep(interval)

from typer.testing import CliRunner

import plextrakt.cli as cli
from plextrakt.sync.report import SyncReport

runner = CliRunner()


class FakeEngine:
    def __init__(self, report=None, error=None):
        self.report = report or SyncReport(to_trakt=2, to_plex=1)
        self.error = error

    def run(self):
        if self.error:
            raise self.error
        return self.report


class FakeContext:
    def __init__(self, engine):
        self._engine = engine

        class S:  # minimal settings stand-in
            log_level = "INFO"
            log_format = "console"
            metrics_port = 0
            sync_interval_seconds = 3600

        self.settings = S()

    def engine(self):
        return self._engine


def test_sync_prints_report_and_exits_zero(monkeypatch):
    monkeypatch.setattr(cli, "build_context", lambda: FakeContext(FakeEngine()))
    result = runner.invoke(cli.app, ["sync"])
    assert result.exit_code == 0
    assert "to_trakt=2" in result.output
    assert "to_plex=1" in result.output


def test_sync_fatal_error_exits_nonzero(monkeypatch):
    monkeypatch.setattr(
        cli, "build_context", lambda: FakeContext(FakeEngine(error=RuntimeError("trakt down")))
    )
    result = runner.invoke(cli.app, ["sync"])
    assert result.exit_code == 1


def test_help_lists_commands():
    result = runner.invoke(cli.app, ["--help"])
    for cmd in ("login", "sync", "watch", "run"):
        assert cmd in result.output


def test_engine_gets_fresh_resolver_per_run(monkeypatch):
    for k, v in {
        "PLEX_URL": "http://plex:32400",
        "PLEX_TOKEN": "t",
        "TRAKT_CLIENT_ID": "c",
        "TRAKT_CLIENT_SECRET": "s",
        "STATE_DIR": "/tmp/plextrakt-test-state",
    }.items():
        monkeypatch.setenv(k, v)
    ctx = cli.AppContext()
    monkeypatch.setattr(type(ctx), "plex", property(lambda self: object()))
    e1, e2 = ctx.engine(), ctx.engine()
    assert e1._resolver is not e2._resolver

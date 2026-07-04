import json

import structlog
from prometheus_client import generate_latest

from plextrakt.obs import metrics
from plextrakt.obs.logging import configure_logging


def test_json_logging(capsys):
    configure_logging("INFO", "json")
    structlog.get_logger().info("sync_done", to_trakt=3)
    line = capsys.readouterr().out.strip().splitlines()[-1]
    payload = json.loads(line)
    assert payload["event"] == "sync_done"
    assert payload["to_trakt"] == 3
    assert "timestamp" in payload


def test_log_level_filters(capsys):
    configure_logging("WARNING", "json")
    structlog.get_logger().info("hidden")
    assert capsys.readouterr().out.strip() == ""


def test_metrics_registered():
    metrics.SYNC_ITEMS.labels(direction="to_trakt", outcome="synced").inc()
    metrics.SCROBBLES.labels(action="scrobble").inc()
    out = generate_latest().decode()
    assert 'plextrakt_sync_items_total{direction="to_trakt",outcome="synced"}' in out
    assert "plextrakt_scrobbles_total" in out
    assert "plextrakt_sync_last_success_timestamp" in out

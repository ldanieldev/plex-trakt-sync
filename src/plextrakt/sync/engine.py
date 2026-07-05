import time
from datetime import UTC, datetime

import structlog

from plextrakt.matching.resolver import MATCHED
from plextrakt.obs import metrics
from plextrakt.sync.report import SyncReport

log = structlog.get_logger()


def _iso(epoch: int | None) -> str:
    dt = datetime.fromtimestamp(epoch, tz=UTC) if epoch else datetime.now(tz=UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


class _TraktWatched:
    def __init__(self, movies: list[dict], episodes: list[dict]):
        self._movie_ids: set[tuple[str, object]] = set()
        for row in movies:
            for k, v in row["movie"]["ids"].items():
                if isinstance(v, (str, int)):
                    self._movie_ids.add((k, v))
        self._episode_ids: set[tuple[str, str | int]] = set()
        for row in episodes:
            for k, v in row["episode"]["ids"].items():
                if isinstance(v, (str, int)):
                    self._episode_ids.add((k, v))

    def movie_watched(self, ids) -> bool:
        return any((k, v) in self._movie_ids for k, v in ids.to_dict().items())

    def episode_watched(self, ids) -> bool:
        return any((k, v) in self._episode_ids for k, v in ids.to_dict().items())


class SyncEngine:
    def __init__(self, plex, trakt, resolver, db, now=time.time):
        self._plex = plex
        self._trakt = trakt
        self._resolver = resolver
        self._db = db
        self._now = now

    def run(self) -> SyncReport:
        report = SyncReport()
        watched = _TraktWatched(self._trakt.watched_movies(), self._trakt.watched_episodes())
        queue_movies: list[tuple[dict, str]] = []
        queue_episodes: list[tuple[dict, str]] = []
        scrobbled = self._db.scrobbled_ids()
        fallback_counts: dict[str, int] = {}

        for item in self._plex.scan():
            try:
                self._handle(
                    item, watched, report, queue_movies, queue_episodes, scrobbled, fallback_counts
                )
            except Exception:
                report.errors += 1
                metrics.SYNC_ITEMS.labels(direction="to_trakt", outcome="error").inc()
                log.exception("sync_item_failed", title=item.title, rating_key=item.rating_key)

        for show, n in fallback_counts.items():
            log.info("ordering_fallback_summary", show=show, episodes=n)

        self._push(report, queue_movies, queue_episodes)
        metrics.SYNC_RUNS.labels(result="ok").inc()
        metrics.LAST_SYNC_SUCCESS.set(self._now())
        log.info("sync_done", **report.as_dict())
        return report

    def _handle(
        self, item, watched, report, queue_movies, queue_episodes, scrobbled, fallback_counts
    ):
        if item.media_type == "movie":
            outcome = self._resolver.resolve_movie(item.rating_key, item.guid, list(item.guids))
            on_trakt = outcome.status == MATCHED and watched.movie_watched(outcome.ids)
        else:
            show = self._resolver.resolve_show(item.show_guid, list(item.show_guids))
            outcome = self._resolver.resolve_episode(
                show, item.season, item.number, list(item.guids)
            )
            on_trakt = outcome.status == MATCHED and watched.episode_watched(outcome.ids)

        if outcome.status != MATCHED:
            report.add_skip(outcome.status, item.title)
            metrics.SYNC_ITEMS.labels(direction="to_trakt", outcome="skipped_unmatched").inc()
            return
        if outcome.ordering_fallback:
            report.add_skip("ordering-mismatch-resolved", item.title)
            key = item.show_title or item.show_guid or "unknown"
            fallback_counts[key] = fallback_counts.get(key, 0) + 1

        if item.watched and not on_trakt:
            if any((item.media_type, v) in scrobbled for v in outcome.ids.to_dict().values()):
                return  # scrobbled since last sync; trakt fetch may not reflect it yet
            payload = {"ids": outcome.ids.to_dict(), "watched_at": _iso(item.last_viewed_at)}
            (queue_movies if item.media_type == "movie" else queue_episodes).append(
                (payload, item.title)
            )
        elif on_trakt and not item.watched:
            self._plex.mark_watched(item.rating_key)
            report.to_plex += 1
            metrics.SYNC_ITEMS.labels(direction="to_plex", outcome="synced").inc()

    def _push(self, report, queue_movies, queue_episodes):
        if not queue_movies and not queue_episodes:
            return
        result = self._trakt.add_history(
            movies=[p for p, _ in queue_movies], episodes=[p for p, _ in queue_episodes]
        )
        missed = {
            frozenset(m["ids"].items())
            for kind in ("movies", "shows", "seasons", "episodes")
            for m in result.get("not_found", {}).get(kind, [])
        }
        for payload, title in queue_movies + queue_episodes:
            if frozenset(payload["ids"].items()) in missed:
                report.add_skip("not-found-on-trakt", title)
                metrics.SYNC_ITEMS.labels(direction="to_trakt", outcome="skipped_unmatched").inc()
            else:
                report.to_trakt += 1
                metrics.SYNC_ITEMS.labels(direction="to_trakt", outcome="synced").inc()

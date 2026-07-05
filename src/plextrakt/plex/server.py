from collections.abc import Iterator
from dataclasses import dataclass

import structlog

from plextrakt.matching.guid import ParsedGuid, parse_guid

log = structlog.get_logger()


@dataclass(frozen=True)
class PlexItem:
    rating_key: int
    media_type: str
    title: str
    guid: str
    guids: tuple[ParsedGuid, ...]
    watched: bool
    last_viewed_at: int | None
    duration_ms: int | None
    show_guid: str | None = None
    show_guids: tuple[ParsedGuid, ...] = ()
    season: int | None = None
    number: int | None = None


def _parse_all(raw_guids) -> tuple[ParsedGuid, ...]:
    parsed = (parse_guid(g.id) for g in raw_guids or [])
    return tuple(p for p in parsed if p is not None)


def _guids_with_fallback(raw_guids, guid_str: str) -> tuple[ParsedGuid, ...]:
    parsed = _parse_all(raw_guids)
    if parsed:
        return parsed
    fallback = parse_guid(guid_str)
    return (fallback,) if fallback is not None else ()


def _epoch(dt) -> int | None:
    return int(dt.timestamp()) if dt else None


class PlexLibrary:
    def __init__(self, server):
        self._server = server

    def scan(self) -> Iterator[PlexItem]:
        for section in self._server.library.sections():
            if section.type == "movie":
                yield from self._scan_movies(section)
            elif section.type == "show":
                yield from self._scan_episodes(section)

    def _scan_movies(self, section) -> Iterator[PlexItem]:
        for m in section.search(libtype="movie"):
            yield PlexItem(
                rating_key=int(m.ratingKey),
                media_type="movie",
                title=m.title,
                guid=m.guid,
                guids=_guids_with_fallback(m.guids, m.guid),
                watched=bool(m.viewCount),
                last_viewed_at=_epoch(m.lastViewedAt),
                duration_ms=m.duration,
            )

    def _scan_episodes(self, section) -> Iterator[PlexItem]:
        shows = {
            int(s.ratingKey): (s.guid, _guids_with_fallback(s.guids, s.guid))
            for s in section.search(libtype="show")
        }
        for ep in section.search(libtype="episode"):
            show_guid, show_guids = shows.get(int(ep.grandparentRatingKey), (None, ()))
            yield PlexItem(
                rating_key=int(ep.ratingKey),
                media_type="episode",
                title=ep.title,
                guid=ep.guid,
                guids=_parse_all(ep.guids),
                watched=bool(ep.viewCount),
                last_viewed_at=_epoch(ep.lastViewedAt),
                duration_ms=ep.duration,
                show_guid=show_guid or ep.grandparentGuid,
                show_guids=show_guids,
                season=ep.parentIndex,
                number=ep.index,
            )

    def mark_watched(self, rating_key: int) -> None:
        self._server.fetchItem(int(rating_key)).markWatched()

    def owner_session(self, session_key) -> PlexItem | None:
        session = next(
            (s for s in self._server.sessions() if str(s.sessionKey) == str(session_key)),
            None,
        )
        if session is None or getattr(session.user, "id", None) != 1:
            return None
        item = self._server.fetchItem(int(session.ratingKey))
        if item.type == "movie":
            return PlexItem(
                rating_key=int(item.ratingKey),
                media_type="movie",
                title=item.title,
                guid=item.guid,
                guids=_guids_with_fallback(item.guids, item.guid),
                watched=bool(item.viewCount),
                last_viewed_at=_epoch(item.lastViewedAt),
                duration_ms=item.duration,
            )
        show = self._server.fetchItem(int(item.grandparentRatingKey))
        return PlexItem(
            rating_key=int(item.ratingKey),
            media_type="episode",
            title=item.title,
            guid=item.guid,
            guids=_parse_all(item.guids),
            watched=bool(item.viewCount),
            last_viewed_at=_epoch(item.lastViewedAt),
            duration_ms=item.duration,
            show_guid=show.guid,
            show_guids=_guids_with_fallback(show.guids, show.guid),
            season=item.parentIndex,
            number=item.index,
        )

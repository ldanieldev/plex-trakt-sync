import time
from dataclasses import dataclass

import structlog

from plextrakt.matching.resolver import MATCHED
from plextrakt.obs import metrics

log = structlog.get_logger()

_IGNORED = object()


@dataclass
class _Session:
    payload_media: dict  # {"movie": {...}} or {"episode": {...}}
    media_type: str  # "movie" | "episode"
    duration_ms: int
    last_state: str | None = None


class Scrobbler:
    def __init__(self, plex, trakt, resolver, db, now=time.time):
        self._plex = plex
        self._trakt = trakt
        self._resolver = resolver
        self._db = db
        self._now = now
        self._sessions: dict[str, object] = {}

    def handle_playing(self, notification: dict) -> None:
        state = notification.get("state")
        key = str(notification.get("sessionKey"))
        if state == "buffering":
            return

        session = self._sessions.get(key)
        if session is _IGNORED:
            return
        if session is None:
            if state == "stopped":
                return  # can't attribute a session we never saw
            session = self._open_session(key)
            if session is _IGNORED:
                return

        progress = self._progress(notification, session)

        if state == "playing" and session.last_state != "playing":
            self._call("start", session, progress)
        elif state == "paused" and session.last_state == "playing":
            self._call("pause", session, progress)
        elif state == "stopped":
            result = self._call("stop", session, progress)
            self._finish(session, result)
            del self._sessions[key]
            return
        session.last_state = state

    def _open_session(self, key: str):
        item = self._plex.owner_session(key)
        if item is None:
            self._sessions[key] = _IGNORED
            return _IGNORED
        payload = self._build_payload(item)
        if payload is None:
            self._sessions[key] = _IGNORED
            return _IGNORED
        session = _Session(payload, item.media_type, item.duration_ms or 1)
        self._sessions[key] = session
        return session

    def _build_payload(self, item) -> dict | None:
        if item.media_type == "movie":
            outcome = self._resolver.resolve_movie(item.rating_key, item.guid, list(item.guids))
            if outcome.status != MATCHED:
                log.warning("scrobble_unmatched", title=item.title, status=outcome.status)
                return None
            return {"movie": {"ids": outcome.ids.to_dict()}}
        show = self._resolver.resolve_show(item.show_guid, list(item.show_guids))
        outcome = self._resolver.resolve_episode(show, item.season, item.number, list(item.guids))
        if outcome.status != MATCHED:
            log.warning("scrobble_unmatched", title=item.title, status=outcome.status)
            return None
        return {"episode": {"ids": {"trakt": outcome.ids.trakt}}}

    @staticmethod
    def _progress(notification: dict, session: _Session) -> float:
        offset = notification.get("viewOffset") or 0
        return round(min(max(offset / session.duration_ms * 100, 0.0), 100.0), 2)

    def _call(self, action: str, session: _Session, progress: float) -> dict:
        result = self._trakt.scrobble(action, {**session.payload_media, "progress": progress})
        metrics.SCROBBLES.labels(action=result.get("action", action)).inc()
        log.info("scrobble", action=result.get("action", action), progress=progress)
        return result

    def _finish(self, session: _Session, result: dict) -> None:
        if result.get("action") != "scrobble":
            return
        ids = result.get(session.media_type, {}).get("ids", {})
        recorded = False
        for key in ("trakt", "imdb", "tmdb", "tvdb"):
            v = ids.get(key)
            if v is not None:
                self._db.record_scrobble(session.media_type, v, int(self._now()))
                recorded = True
        if not recorded:
            log.warning("scrobble_response_missing_id", media_type=session.media_type)

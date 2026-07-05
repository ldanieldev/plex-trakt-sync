import time

import httpx
import structlog

from plextrakt import __version__
from plextrakt.obs import metrics

BASE = "https://api.trakt.tv"
CHUNK = 200
MAX_ATTEMPTS = 3

log = structlog.get_logger()


class TraktError(Exception):
    pass


class TraktClient:
    def __init__(self, auth, limiter, http: httpx.Client, sleep=time.sleep):
        self._auth = auth
        self._limiter = limiter
        self._http = http
        self._sleep = sleep

    # -- public API --------------------------------------------------------

    def watched_movies(self) -> list[dict]:
        return self._get_all_pages("/sync/watched/movies")

    def watched_episodes(self) -> list[dict]:
        return self._get_all_pages("/sync/watched/episodes", params={"limit": 1000})

    def add_history(self, movies=(), episodes=()) -> dict:
        items = [("movies", m) for m in movies] + [("episodes", e) for e in episodes]
        merged = {"added": {}, "not_found": {}}
        for start in range(0, len(items), CHUNK):
            body: dict = {}
            for kind, item in items[start : start + CHUNK]:
                body.setdefault(kind, []).append(item)
            resp = self._post("/sync/history", body)
            for kind, count in resp.get("added", {}).items():
                merged["added"][kind] = merged["added"].get(kind, 0) + count
            for kind, misses in resp.get("not_found", {}).items():
                merged["not_found"].setdefault(kind, []).extend(misses)
        return merged

    def scrobble(self, action: str, payload: dict) -> dict:
        resp = self._request("POST", f"/scrobble/{action}", json=payload, write=True, allow={409})
        if resp.status_code == 409:
            return {"action": "duplicate", **resp.json()}
        return resp.json()

    def lookup_id(self, id_type, id_value, media_type: str) -> dict | None:
        results = self._get(f"/search/{id_type}/{id_value}", params={"type": media_type})
        for entry in results:
            if entry.get("type") == media_type and media_type in entry:
                return entry[media_type]
        return None

    def episode_table(self, show_trakt_id: int) -> list[dict]:
        seasons = self._get(f"/shows/{show_trakt_id}/seasons", params={"extended": "episodes"})
        return [
            {"season": ep["season"], "number": ep["number"], "ids": ep["ids"]}
            for season in seasons
            for ep in season.get("episodes", [])
        ]

    # -- plumbing ----------------------------------------------------------

    def _headers(self) -> dict:
        return {
            "Content-Type": "application/json",
            "User-Agent": f"plextrakt/{__version__}",
            "trakt-api-version": "2",
            "trakt-api-key": self._auth.client_id,
            "Authorization": f"Bearer {self._auth.access_token()}",
        }

    def _get(self, path: str, params: dict | None = None):
        return self._request("GET", path, params=params).json()

    def _get_all_pages(self, path: str, params: dict | None = None) -> list:
        params = dict(params or {})
        params.setdefault("limit", 100)
        page = 1
        out: list = []
        while True:
            resp = self._request("GET", path, params={**params, "page": page})
            out.extend(resp.json())
            page_count = int(resp.headers.get("X-Pagination-Page-Count", "1"))
            if page >= page_count:
                return out
            page += 1

    def _post(self, path: str, body: dict):
        return self._request("POST", path, json=body, write=True).json()

    def _request(self, method, path, params=None, json=None, write=False, allow=frozenset()):
        refreshed = False
        for _attempt in range(MAX_ATTEMPTS):
            if write:
                self._limiter.wait()
            resp = self._http.request(
                method, f"{BASE}{path}", params=params, json=json, headers=self._headers()
            )
            metrics.TRAKT_REQUESTS.labels(status=str(resp.status_code)).inc()
            if resp.status_code == 429:
                metrics.TRAKT_RATE_LIMITED.inc()
                retry_after = float(resp.headers.get("Retry-After", "1"))
                log.warning("trakt_rate_limited", retry_after=retry_after)
                self._sleep(retry_after)
                continue
            if resp.status_code == 401 and not refreshed:
                log.info("trakt_token_refresh", reason="401")
                self._auth.refresh()
                refreshed = True
                continue
            if resp.is_success or resp.status_code in allow:
                return resp
            raise TraktError(f"{method} {path} -> {resp.status_code}: {resp.text[:200]}")
        raise TraktError(f"{method} {path} -> gave up after {MAX_ATTEMPTS} attempts")

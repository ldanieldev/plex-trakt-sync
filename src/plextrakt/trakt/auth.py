import time

import httpx
import structlog

BASE = "https://api.trakt.tv"
_FATAL_POLL = {
    404: "invalid_device_code",
    409: "already_approved",
    410: "code_expired",
    418: "denied",
}

log = structlog.get_logger()


class TraktAuthError(Exception):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


class TraktAuth:
    def __init__(
        self, client_id, client_secret, db, http: httpx.Client, sleep=time.sleep, now=time.time
    ):
        self.client_id = client_id  # public: TraktClient needs it for trakt-api-key
        self._client_secret = client_secret
        self._db = db
        self._http = http
        self._sleep = sleep
        self._now = now

    def request_device_code(self) -> dict:
        resp = self._http.post(f"{BASE}/oauth/device/code", json={"client_id": self.client_id})
        resp.raise_for_status()
        return resp.json()

    def poll_device_token(self, device: dict):
        interval = device["interval"]
        deadline = self._now() + device["expires_in"]
        while self._now() < deadline:
            resp = self._http.post(
                f"{BASE}/oauth/device/token",
                json={
                    "code": device["device_code"],
                    "client_id": self.client_id,
                    "client_secret": self._client_secret,
                },
            )
            if resp.status_code == 200:
                return self._store(resp.json())
            if resp.status_code == 400:
                self._sleep(interval)
                continue
            if resp.status_code == 429:
                interval += 1
                self._sleep(interval)
                continue
            if resp.status_code in _FATAL_POLL:
                raise TraktAuthError(_FATAL_POLL[resp.status_code])
            resp.raise_for_status()
        raise TraktAuthError("code_expired")

    def refresh(self):
        pair = self._db.load_tokens()
        if pair is None:
            raise TraktAuthError("login_required")
        resp = self._http.post(
            f"{BASE}/oauth/token",
            json={
                "refresh_token": pair.refresh_token,
                "client_id": self.client_id,
                "client_secret": self._client_secret,
                "redirect_uri": "urn:ietf:wg:oauth:2.0:oob",
                "grant_type": "refresh_token",
            },
        )
        if resp.status_code in (400, 401):
            raise TraktAuthError("login_required")
        resp.raise_for_status()
        return self._store(resp.json())

    def access_token(self) -> str:
        pair = self._db.load_tokens()
        if pair is None:
            raise TraktAuthError("login_required")
        if self._now() >= pair.refresh_after:
            log.info("trakt_token_refresh", reason="proactive")
            pair = self.refresh()
        return pair.access_token

    def _store(self, payload: dict):
        from plextrakt.state.db import TokenPair

        pair = TokenPair(
            access_token=payload["access_token"],
            refresh_token=payload["refresh_token"],
            created_at=int(payload.get("created_at") or self._now()),
            expires_in=int(payload["expires_in"]),
        )
        self._db.save_tokens(pair)
        return pair

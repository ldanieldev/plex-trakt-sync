import httpx
import pytest
import respx

from plextrakt.state.db import StateDB, TokenPair
from plextrakt.trakt.auth import TraktAuth, TraktAuthError

TOKENS = {
    "access_token": "acc1",
    "refresh_token": "ref1",
    "expires_in": 86400,
    "created_at": 1720000000,
    "token_type": "bearer",
    "scope": "public",
}


def make_auth(tmp_path, now=lambda: 1720000000.0):
    db = StateDB(tmp_path / "state.db")
    auth = TraktAuth("cid", "csec", db, httpx.Client(), sleep=lambda s: None, now=now)
    return auth, db


@respx.mock
def test_device_flow_polls_until_approved(tmp_path):
    respx.post("https://api.trakt.tv/oauth/device/code").respond(
        200,
        json={
            "device_code": "dev1",
            "user_code": "5055CC52",
            "verification_url": "https://trakt.tv/activate",
            "expires_in": 600,
            "interval": 5,
        },
    )
    token_route = respx.post("https://api.trakt.tv/oauth/device/token")
    token_route.side_effect = [
        httpx.Response(400),
        httpx.Response(400),
        httpx.Response(200, json=TOKENS),
    ]
    auth, db = make_auth(tmp_path)
    device = auth.request_device_code()
    pair = auth.poll_device_token(device)
    assert pair.access_token == "acc1"
    assert db.load_tokens().refresh_token == "ref1"
    assert token_route.call_count == 3


@respx.mock
def test_device_flow_denied_raises(tmp_path):
    respx.post("https://api.trakt.tv/oauth/device/token").respond(418)
    auth, _ = make_auth(tmp_path)
    with pytest.raises(TraktAuthError):
        auth.poll_device_token({"device_code": "dev1", "expires_in": 600, "interval": 5})


@respx.mock
def test_refresh_rotates_and_persists(tmp_path):
    auth, db = make_auth(tmp_path)
    db.save_tokens(TokenPair("old_acc", "old_ref", 1719000000, 86400))
    route = respx.post("https://api.trakt.tv/oauth/token").respond(
        200, json={**TOKENS, "access_token": "acc2", "refresh_token": "ref2"}
    )
    pair = auth.refresh()
    assert pair.access_token == "acc2"
    assert db.load_tokens().refresh_token == "ref2"
    body = route.calls[0].request.content.decode()
    assert '"grant_type": "refresh_token"' in body or '"grant_type":"refresh_token"' in body


@respx.mock
def test_access_token_refreshes_when_stale(tmp_path):
    # created 1719000000, expires_in 86400 -> refresh_after = 1719069120
    auth, db = make_auth(tmp_path, now=lambda: 1719100000.0)
    db.save_tokens(TokenPair("old_acc", "old_ref", 1719000000, 86400))
    respx.post("https://api.trakt.tv/oauth/token").respond(
        200, json={**TOKENS, "access_token": "acc2", "refresh_token": "ref2"}
    )
    assert auth.access_token() == "acc2"


def test_access_token_without_login_raises(tmp_path):
    auth, _ = make_auth(tmp_path)
    with pytest.raises(TraktAuthError):
        auth.access_token()


@respx.mock
def test_concurrent_refresh_fires_once(tmp_path):
    import threading

    auth, db = make_auth(tmp_path, now=lambda: 1719100000.0)
    db.save_tokens(TokenPair("old_acc", "old_ref", 1719000000, 86400))
    route = respx.post("https://api.trakt.tv/oauth/token").respond(
        200, json={**TOKENS, "access_token": "acc2", "refresh_token": "ref2"}
    )
    barrier = threading.Barrier(2)
    results = []

    def worker():
        barrier.wait()
        results.append(auth.access_token())

    threads = [threading.Thread(target=worker) for _ in range(2)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert results == ["acc2", "acc2"]
    assert route.call_count == 1

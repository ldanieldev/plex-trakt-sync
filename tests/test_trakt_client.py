import httpx
import pytest
import respx

from plextrakt.trakt.client import TraktClient, TraktError


class FakeAuth:
    client_id = "cid"

    def __init__(self):
        self.refreshed = 0

    def access_token(self):
        return "acc"

    def refresh(self):
        self.refreshed += 1


class NoopLimiter:
    def __init__(self):
        self.waits = 0

    def wait(self):
        self.waits += 1


def make_client():
    return TraktClient(FakeAuth(), NoopLimiter(), httpx.Client()), None


@respx.mock
def test_headers_sent():
    route = respx.get("https://api.trakt.tv/sync/watched/movies").respond(200, json=[])
    client, _ = make_client()
    client.watched_movies()
    req = route.calls[0].request
    assert req.headers["trakt-api-version"] == "2"
    assert req.headers["trakt-api-key"] == "cid"
    assert req.headers["authorization"] == "Bearer acc"
    assert req.headers["content-type"] == "application/json"
    assert "plextrakt/" in req.headers["user-agent"]


@respx.mock
def test_429_retries_with_retry_after():
    route = respx.get("https://api.trakt.tv/sync/watched/episodes")
    route.side_effect = [
        httpx.Response(429, headers={"Retry-After": "0"}),
        httpx.Response(200, json=[{"episode": {}}]),
    ]
    client, _ = make_client()
    assert client.watched_episodes() == [{"episode": {}}]
    assert route.call_count == 2


@respx.mock
def test_add_history_chunks_at_200():
    route = respx.post("https://api.trakt.tv/sync/history").respond(
        201,
        json={
            "added": {"movies": 0, "episodes": 100},
            "not_found": {"movies": [], "shows": [], "seasons": [], "episodes": []},
        },
    )
    client, _ = make_client()
    episodes = [{"ids": {"trakt": i}} for i in range(450)]
    result = client.add_history(episodes=episodes)
    assert route.call_count == 3  # 200 + 200 + 50
    assert result["added"]["episodes"] == 300


@respx.mock
def test_add_history_merges_not_found():
    route = respx.post("https://api.trakt.tv/sync/history")
    route.side_effect = [
        httpx.Response(
            201,
            json={
                "added": {"movies": 1, "episodes": 0},
                "not_found": {
                    "movies": [{"ids": {"imdb": "tt0000111"}}],
                    "shows": [],
                    "seasons": [],
                    "episodes": [],
                },
            },
        )
    ]
    client, _ = make_client()
    result = client.add_history(movies=[{"ids": {"imdb": "tt1"}}, {"ids": {"imdb": "tt0000111"}}])
    assert result["not_found"]["movies"] == [{"ids": {"imdb": "tt0000111"}}]


@respx.mock
def test_scrobble_409_is_duplicate_not_error():
    respx.post("https://api.trakt.tv/scrobble/stop").respond(
        409, json={"watched_at": "2026-01-01T00:00:00.000Z"}
    )
    client, _ = make_client()
    result = client.scrobble("stop", {"movie": {"ids": {"tmdb": 1}}, "progress": 95.0})
    assert result["action"] == "duplicate"


@respx.mock
def test_lookup_id_empty_returns_none():
    respx.get("https://api.trakt.tv/search/tmdb/999999?type=show").respond(200, json=[])
    client, _ = make_client()
    assert client.lookup_id("tmdb", 999999, "show") is None


@respx.mock
def test_lookup_id_returns_inner_object():
    respx.get("https://api.trakt.tv/search/tmdb/1429?type=show").respond(
        200,
        json=[
            {
                "type": "show",
                "score": 100.0,
                "show": {"title": "AoT", "ids": {"trakt": 1420, "tmdb": 1429}},
            }
        ],
    )
    client, _ = make_client()
    assert client.lookup_id("tmdb", 1429, "show")["ids"]["trakt"] == 1420


@respx.mock
def test_episode_table_flattens_seasons():
    respx.get("https://api.trakt.tv/shows/1420/seasons?extended=episodes").respond(
        200,
        json=[
            {
                "number": 1,
                "episodes": [
                    {"season": 1, "number": 1, "ids": {"trakt": 10, "tvdb": 100}},
                    {"season": 1, "number": 2, "ids": {"trakt": 11, "tvdb": 101}},
                ],
            },
            {
                "number": 2,
                "episodes": [
                    {"season": 2, "number": 1, "ids": {"trakt": 20, "tvdb": 200}},
                ],
            },
        ],
    )
    client, _ = make_client()
    table = client.episode_table(1420)
    assert len(table) == 3
    assert table[2] == {"season": 2, "number": 1, "ids": {"trakt": 20, "tvdb": 200}}


@respx.mock
def test_server_error_raises_trakt_error():
    respx.get("https://api.trakt.tv/sync/watched/movies").respond(500)
    client, _ = make_client()
    with pytest.raises(TraktError):
        client.watched_movies()


@respx.mock
def test_401_refreshes_once_and_retries():
    route = respx.get("https://api.trakt.tv/sync/watched/movies")
    route.side_effect = [
        httpx.Response(401),
        httpx.Response(200, json=[]),
    ]
    auth = FakeAuth()
    client = TraktClient(auth, NoopLimiter(), httpx.Client())
    assert client.watched_movies() == []
    assert auth.refreshed == 1
    assert route.call_count == 2


@respx.mock
def test_add_history_mixed_batch_chunks_correctly():
    bodies = []

    def capture(request):
        import json as _json

        bodies.append(_json.loads(request.content))
        return httpx.Response(
            201,
            json={
                "added": {"movies": 0, "episodes": 0},
                "not_found": {"movies": [], "shows": [], "seasons": [], "episodes": []},
            },
        )

    respx.post("https://api.trakt.tv/sync/history").mock(side_effect=capture)
    client, _ = make_client()
    movies = [{"ids": {"tmdb": i}} for i in range(150)]
    episodes = [{"ids": {"trakt": i}} for i in range(100)]
    client.add_history(movies=movies, episodes=episodes)
    assert len(bodies) == 2  # 150 movies + 50 episodes, then 50 episodes
    assert len(bodies[0]["movies"]) == 150 and len(bodies[0]["episodes"]) == 50
    assert "movies" not in bodies[1] and len(bodies[1]["episodes"]) == 50


@respx.mock
def test_watched_movies_follows_pagination():
    route = respx.get("https://api.trakt.tv/sync/watched/movies")
    route.side_effect = [
        httpx.Response(
            200,
            json=[{"movie": {"ids": {"trakt": i}}} for i in range(100)],
            headers={"X-Pagination-Page": "1", "X-Pagination-Page-Count": "3"},
        ),
        httpx.Response(
            200,
            json=[{"movie": {"ids": {"trakt": i}}} for i in range(100, 200)],
            headers={"X-Pagination-Page": "2", "X-Pagination-Page-Count": "3"},
        ),
        httpx.Response(
            200,
            json=[{"movie": {"ids": {"trakt": i}}} for i in range(200, 237)],
            headers={"X-Pagination-Page": "3", "X-Pagination-Page-Count": "3"},
        ),
    ]
    client, _ = make_client()
    rows = client.watched_movies()
    assert len(rows) == 237
    assert route.call_count == 3
    # each request must carry explicit page + limit params
    assert "page=1" in str(route.calls[0].request.url)
    assert "page=3" in str(route.calls[2].request.url)


@respx.mock
def test_watched_episodes_single_page_without_headers():
    respx.get("https://api.trakt.tv/sync/watched/episodes").respond(200, json=[{"episode": {}}])
    client, _ = make_client()
    assert client.watched_episodes() == [{"episode": {}}]

import types
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest


class FakeGuidTag:
    def __init__(self, id: str):
        self.id = id


@dataclass
class FakeMovie:
    ratingKey: int
    title: str
    guid: str
    guids: list
    viewCount: int = 0
    lastViewedAt: datetime | None = None
    duration: int | None = 6_000_000
    type: str = "movie"
    marked: bool = False

    def markWatched(self):
        self.marked = True


@dataclass
class FakeShow:
    ratingKey: int
    guid: str
    guids: list
    type: str = "show"


@dataclass
class FakeEpisode:
    ratingKey: int
    title: str
    guid: str
    guids: list
    grandparentRatingKey: int
    grandparentGuid: str
    parentIndex: int
    index: int
    viewCount: int = 0
    lastViewedAt: datetime | None = None
    duration: int | None = 1_500_000
    type: str = "episode"
    marked: bool = False
    grandparentTitle: str = ""

    def markWatched(self):
        self.marked = True


@dataclass
class FakeSection:
    type: str  # "movie" | "show"
    movies: list = field(default_factory=list)
    shows: list = field(default_factory=list)
    episodes: list = field(default_factory=list)
    title: str = ""

    def search(self, libtype=None, **kwargs):
        return {"movie": self.movies, "show": self.shows, "episode": self.episodes}[libtype]


class FakeUser:
    def __init__(self, id: int):
        self.id = id


@dataclass
class FakeSession:
    sessionKey: int
    ratingKey: int
    user: FakeUser
    _userId: int | None = None


class FakeLibrary:
    def __init__(self, sections):
        self._sections = sections

    def sections(self):
        return self._sections


class FakePlexServer:
    def __init__(self, sections=(), items=(), sessions=(), owner_id: int = 7742299):
        self.library = FakeLibrary(list(sections))
        self._items = {i.ratingKey: i for i in items}
        self._sessions = list(sessions)
        self._owner_id = owner_id

    def fetchItem(self, rating_key):
        return self._items[int(rating_key)]

    def sessions(self):
        return self._sessions

    def myPlexAccount(self):
        return types.SimpleNamespace(id=self._owner_id)


def dt(epoch: int) -> datetime:
    return datetime.fromtimestamp(epoch, tz=UTC)


@pytest.fixture
def reset_structlog():
    """Reset structlog to default configuration for capture_logs testing."""
    import structlog

    # Clear any previous structlog configuration
    structlog.reset_defaults()
    yield
    # Reset again after the test
    structlog.reset_defaults()

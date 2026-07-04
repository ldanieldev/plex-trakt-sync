from dataclasses import dataclass
from urllib.parse import urlparse

_AGENT_PREFIX = "com.plexapp.agents."
_NORMALIZE = {"themoviedb": "tmdb", "thetvdb": "tvdb", "xbmcnfotv": "tvdb"}
_EXTERNAL = ("imdb", "tmdb", "tvdb")


@dataclass(frozen=True)
class ParsedGuid:
    provider: str
    id: str
    season: int | None = None
    episode: int | None = None


def parse_guid(raw: str) -> ParsedGuid | None:
    if not raw or "://" not in raw:
        return None
    parsed = urlparse(raw)
    provider = parsed.scheme
    rest = (parsed.netloc + parsed.path).strip("/")
    if provider.startswith(_AGENT_PREFIX):
        provider = provider.removeprefix(_AGENT_PREFIX)
    provider = _NORMALIZE.get(provider, provider)
    if not rest:
        return None
    parts = rest.split("/")
    if provider == "tvdb" and len(parts) == 3 and all(p.isdigit() for p in parts):
        return ParsedGuid(provider, parts[0], season=int(parts[1]), episode=int(parts[2]))
    if provider == "plex":
        # plex://movie/<hash> -> keep the hash as the id
        return ParsedGuid(provider, parts[-1])
    return ParsedGuid(provider, parts[0])


def external_ids(guids: list[ParsedGuid | None]) -> dict[str, str | int]:
    out: dict[str, str | int] = {}
    for g in guids:
        if g is None or g.provider not in _EXTERNAL:
            continue
        out[g.provider] = g.id if g.provider == "imdb" else int(g.id)
    return out

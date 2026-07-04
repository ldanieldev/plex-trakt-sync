import time
from dataclasses import dataclass

import structlog

from plextrakt.matching.guid import ParsedGuid, external_ids
from plextrakt.state.db import TraktIds

MATCHED = "matched"
UNMATCHED_IN_PLEX = "unmatched-in-plex"
SHOW_MISSING = "show-missing-on-trakt"
EPISODE_MISSING = "episode-missing-on-trakt"

_ID_ORDER = ("tmdb", "tvdb", "imdb")

log = structlog.get_logger()


@dataclass
class MatchOutcome:
    status: str
    ids: TraktIds | None = None
    ordering_fallback: bool = False
    season: int | None = None
    number: int | None = None


class Resolver:
    def __init__(self, trakt, db, table_ttl_s: int = 7 * 86400, now=time.time):
        self._trakt = trakt
        self._db = db
        self._table_ttl_s = table_ttl_s
        self._now = now
        self._show_memo: dict[str, MatchOutcome] = {}
        self._tables: dict[int, list[dict]] = {}

    def resolve_movie(self, rating_key, guid, guids: list[ParsedGuid]) -> MatchOutcome:
        ext = external_ids(guids)
        if not ext:
            return MatchOutcome(UNMATCHED_IN_PLEX)
        return MatchOutcome(MATCHED, TraktIds.from_dict(ext))

    def resolve_show(self, show_guid: str, show_guids: list[ParsedGuid]) -> MatchOutcome:
        if show_guid in self._show_memo:
            return self._show_memo[show_guid]
        cached = self._db.get_match(show_guid)
        if cached is not None:
            outcome = MatchOutcome(MATCHED, cached)
            self._show_memo[show_guid] = outcome
            return outcome
        ext = external_ids(show_guids)
        if not ext:
            outcome = MatchOutcome(UNMATCHED_IN_PLEX)
        else:
            outcome = MatchOutcome(SHOW_MISSING)
            for id_type in _ID_ORDER:
                if id_type not in ext:
                    continue
                found = self._trakt.lookup_id(id_type, ext[id_type], "show")
                if found:
                    outcome = MatchOutcome(MATCHED, TraktIds.from_dict(found["ids"]))
                    self._db.set_match(show_guid, outcome.ids)
                    break
        self._show_memo[show_guid] = outcome
        return outcome

    def resolve_episode(
        self, show: MatchOutcome, season: int, number: int, ep_guids: list[ParsedGuid]
    ) -> MatchOutcome:
        if show.status != MATCHED:
            return MatchOutcome(show.status)
        table = self._episode_table(show.ids.trakt)
        ext = external_ids(ep_guids)

        positional = next(
            (e for e in table if e["season"] == season and e["number"] == number), None
        )
        if positional is not None and self._ids_agree(positional["ids"], ext):
            return MatchOutcome(
                MATCHED,
                TraktIds.from_dict(positional["ids"]),
                season=positional["season"],
                number=positional["number"],
            )

        # ordering divergence (or positional miss): reverse-lookup by episode id
        for id_type in ("tvdb", "tmdb", "imdb"):
            if id_type not in ext:
                continue
            hit = next((e for e in table if e["ids"].get(id_type) == ext[id_type]), None)
            if hit is not None:
                log.info(
                    "ordering_fallback",
                    season=season,
                    number=number,
                    matched_season=hit["season"],
                    matched_number=hit["number"],
                )
                return MatchOutcome(
                    MATCHED,
                    TraktIds.from_dict(hit["ids"]),
                    ordering_fallback=True,
                    season=hit["season"],
                    number=hit["number"],
                )
        return MatchOutcome(EPISODE_MISSING)

    def _episode_table(self, show_trakt_id: int) -> list[dict]:
        if show_trakt_id in self._tables:
            return self._tables[show_trakt_id]
        now = int(self._now())
        table = self._db.get_episode_table(show_trakt_id, self._table_ttl_s, now)
        if table is None:
            table = self._trakt.episode_table(show_trakt_id)
            self._db.set_episode_table(show_trakt_id, table, now)
        self._tables[show_trakt_id] = table
        return table

    @staticmethod
    def _ids_agree(trakt_ids: dict, plex_ext: dict) -> bool:
        overlap = [k for k in ("tvdb", "tmdb", "imdb") if k in plex_ext and trakt_ids.get(k)]
        if not overlap:
            return True  # nothing to validate against -> accept positional
        return any(trakt_ids[k] == plex_ext[k] for k in overlap)

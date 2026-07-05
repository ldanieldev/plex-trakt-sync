from dataclasses import dataclass, field


@dataclass
class SyncReport:
    to_trakt: int = 0
    to_plex: int = 0
    errors: int = 0
    skipped: dict[str, list[str]] = field(default_factory=dict)

    def add_skip(self, category: str, title: str) -> None:
        self.skipped.setdefault(category, []).append(title)

    def as_dict(self) -> dict:
        return {
            "to_trakt": self.to_trakt,
            "to_plex": self.to_plex,
            "errors": self.errors,
            "skipped": {k: len(v) for k, v in self.skipped.items()},
        }

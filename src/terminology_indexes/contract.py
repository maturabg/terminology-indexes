"""What enrichment sees: ``Provider.search`` / ``Provider.check`` and their records.

Index and live providers implement the same protocol, so the caller never knows
whether an answer came from ``index.sqlite`` or from an API.
"""

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

MATCH_RANK = {"exact": 0, "alias": 1, "fts": 2}
CHECK_STATUSES = frozenset({"ok", "dead", "unknown", "moved"})


@dataclass(frozen=True)
class Candidate:
    source: str
    external_id: str
    url: str
    title: str
    kind: str  # term | concept | document | spec_section
    matched_label: str
    match: str  # exact | alias | fts
    snippet: str | None
    snapshot_version: str  # release tag / shard version, or live:<date>
    # ``search_all(translation=...)``: the translation's label on the same entry
    also_matched: str | None = None


@dataclass(frozen=True)
class LinkRecord:
    """A stored link, as enrichment keeps it."""

    source: str
    external_id: str
    url: str
    snapshot_version: str | None = None


@dataclass(frozen=True)
class CheckResult:
    status: str  # ok | dead | unknown | moved
    new_url: str | None = None
    reason: str = ""

    def __post_init__(self) -> None:
        if self.status not in CHECK_STATUSES:
            raise ValueError(f"unknown check status {self.status!r}")


@runtime_checkable
class Provider(Protocol):
    id: str

    def search(self, query: str, *, lang: str | None = None, limit: int = 5) -> list[Candidate]: ...

    def check(self, link: LinkRecord) -> CheckResult: ...

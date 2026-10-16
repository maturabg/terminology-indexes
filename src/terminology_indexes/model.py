"""Rows of the index and the source registry."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

SCHEMA_VERSION = 1

KINDS = frozenset({"term", "concept", "document", "spec_section"})
STATUSES = frozenset({"active", "deprecated", "redirect"})
LABEL_TYPES = frozenset({"pref", "alt", "hidden", "redirect"})
SNIPPET_LIMITS = {"none": 0, "short": 200, "full": None}


@dataclass(frozen=True)
class Label:
    label: str
    lang: str | None = None
    label_type: str = "pref"


@dataclass
class Entry:
    external_id: str
    url: str
    title: str
    kind: str
    lang: str | None = None
    status: str = "active"
    replaced_by: str | None = None
    snippet: str | None = None
    extra: dict[str, Any] | None = None
    labels: list[Label] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"{self.external_id}: unknown kind {self.kind!r}")
        if self.status not in STATUSES:
            raise ValueError(f"{self.external_id}: unknown status {self.status!r}")
        for label in self.labels:
            if label.label_type not in LABEL_TYPES:
                raise ValueError(f"{self.external_id}: unknown label_type {label.label_type!r}")


@dataclass(frozen=True)
class Source:
    """One ``sources/<id>.yaml``; unknown keys stay in ``raw``."""

    id: str
    name: str
    mode: str
    status: str
    fetch: dict[str, Any] | None
    langs: list[str]
    kind_default: str
    license_class: str
    snippet_policy: str
    attribution: str
    max_row_drop: float | None
    raw: dict[str, Any]

    @classmethod
    def load(cls, path: Path) -> Source:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if raw["id"] != path.stem:
            raise ValueError(f"{path}: id {raw['id']!r} does not match file name")
        return cls(
            id=raw["id"],
            name=raw["name"],
            mode=raw["mode"],
            status=raw["status"],
            fetch=raw.get("fetch"),
            langs=raw.get("langs") or [],
            kind_default=raw["kind_default"],
            license_class=raw["license"]["class"],
            snippet_policy=raw["snippet_policy"],
            attribution=raw["attribution"],
            max_row_drop=(raw.get("guards") or {}).get("max_row_drop"),
            raw=raw,
        )

    def clip_snippet(self, snippet: str | None) -> str | None:
        """Apply ``snippet_policy`` to a parsed snippet."""
        if not snippet:
            return None
        limit = SNIPPET_LIMITS[self.snippet_policy]
        if limit == 0:
            return None
        if limit is not None and len(snippet) > limit:
            return snippet[: limit - 1].rstrip() + "…"
        return snippet


def load_registry(sources_dir: Path) -> dict[str, Source]:
    return {s.id: s for s in map(Source.load, sorted(sources_dir.glob("*.yaml")))}

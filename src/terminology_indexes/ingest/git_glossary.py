"""Git Glossary from ``Documentation/glossary-content.adoc`` (``[[def_…]]term::``)."""

import re
from collections.abc import Iterator
from pathlib import Path

from terminology_indexes.ingest.base import Adapter, RawSnapshot, download
from terminology_indexes.ingest.text import dedupe, title_variants
from terminology_indexes.model import Entry, Label

BASE = "https://git-scm.com/docs/gitglossary#"

_HEAD = re.compile(r"\[\[(def_[^\]]+)\]\](.+)::")
# "cache:: Obsolete for: <<def_index,index>>." — an old name of another entry.
_OBSOLETE = re.compile(r"\s*Obsolete for:\s*<<(def_[^,>]+)")


def head_labels(head: str) -> list[str]:
    """``object identifier, object ID, oid`` names one term three ways; ``X, Y and Z`` is one name."""
    names = head.split(", ") if " and " not in head else [head]
    return [v for name in names for v in title_variants(name)]


def read_glossary(path: Path) -> list[tuple[str, str, str]]:
    """``[(anchor, head, first line of the definition), ...]``."""
    lines = path.read_text(encoding="utf-8").splitlines()
    out = []
    for i, line in enumerate(lines):
        if m := _HEAD.fullmatch(line.rstrip()):
            out.append((m[1], m[2].strip(), lines[i + 1] if i + 1 < len(lines) else ""))
    return out


class GitGlossary(Adapter):
    def fetch(self, raw_dir: Path) -> RawSnapshot:
        path = raw_dir / self.source.id / "glossary-content.adoc"
        sha = download(self.source.fetch["url"], path)
        return self.snapshot(path, sha)

    def snapshot(self, path: Path, sha: str) -> RawSnapshot:
        # The file has no version; master moves, the hash says whether this one did.
        return RawSnapshot(path=path, sha256=sha, snapshot_version=f"master+{sha[:12]}")

    def parse(self, snapshot: RawSnapshot) -> Iterator[Entry]:
        entries: dict[str, Entry] = {}
        for anchor, head, first in read_glossary(snapshot.path):
            first_label, *rest = head_labels(head)
            entry = Entry(
                external_id=anchor,
                url=BASE + anchor,
                title=head,
                kind=self.source.kind_default,
                lang="en",
                labels=dedupe([Label(first_label, "en", "pref"), *(Label(v, "en", "alt") for v in rest)]),
            )
            if m := _OBSOLETE.match(first):
                entry.status, entry.replaced_by = "redirect", m[1]
            entries[anchor] = entry
        # An obsolete name is searchable as a label of the entry that replaced it.
        for entry in entries.values():
            if entry.status == "redirect" and (target := entries.get(entry.replaced_by)):
                target.labels = dedupe([*target.labels, *(Label(l.label, "en", "redirect") for l in entry.labels)])
        yield from entries.values()

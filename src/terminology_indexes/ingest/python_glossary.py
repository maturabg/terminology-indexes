"""Python Glossary from the Sphinx ``objects.inv`` (``std:term`` only)."""

import re
import zlib
from collections.abc import Iterator
from pathlib import Path

from terminology_indexes.ingest.base import Adapter, RawSnapshot, download
from terminology_indexes.model import Entry, Label

# Fetch is pinned (see the yaml), public links point to /3/ (docs/decisions.md).
PUBLIC_BASE = "https://docs.python.org/3/"

# Same pattern Sphinx uses to read inventory lines; names may contain spaces.
_LINE = re.compile(r"(.+?)\s+(\S+)\s+(-?\d+)\s+?(\S*)\s+(.*)")


def read_inventory(path: Path) -> tuple[str, list[tuple[str, str, str, str]]]:
    """Return ``(version, [(name, domain:role, uri, dispname), ...])``."""
    data = path.read_bytes()
    header, _, body = data.partition(b"\n# The remainder of this file is compressed using zlib.\n")
    lines = header.decode().splitlines()
    if not body or lines[0] != "# Sphinx inventory version 2":
        raise ValueError(f"{path}: not a Sphinx v2 inventory")
    version = next((l.removeprefix("# Version: ") for l in lines if l.startswith("# Version: ")), "")
    items = []
    for line in zlib.decompress(body).decode().splitlines():
        if m := _LINE.fullmatch(line.rstrip()):
            name, role, _prio, uri, dispname = m.groups()
            if uri.endswith("$"):
                uri = uri[:-1] + name
            items.append((name, role, uri, name if dispname == "-" else dispname))
    return version, items


class PythonGlossary(Adapter):
    def fetch(self, raw_dir: Path) -> RawSnapshot:
        path = raw_dir / self.source.id / "objects.inv"
        sha = download(self.source.fetch["url"], path)
        return self.snapshot(path, sha)

    def snapshot(self, path: Path, sha: str) -> RawSnapshot:
        version, _ = read_inventory(path)
        return RawSnapshot(path=path, sha256=sha, snapshot_version=f"{version}+{sha[:12]}")

    def parse(self, snapshot: RawSnapshot) -> Iterator[Entry]:
        _, items = read_inventory(snapshot.path)
        for name, role, uri, dispname in items:
            if role != "std:term":
                continue
            yield Entry(
                external_id=name,  # the std:term key; the anchor is derived from it
                url=PUBLIC_BASE + uri,
                title=dispname,
                kind=self.source.kind_default,
                lang="en",
                labels=[Label(dispname, "en", "pref")],
            )

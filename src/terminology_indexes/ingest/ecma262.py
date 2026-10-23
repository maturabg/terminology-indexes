"""ECMA-262 from the npm package ``@tc39/ecma262-biblio``: defined terms and clauses.

``fetch.version`` is an npm dist-tag or an exact version; the exact one goes into
``snapshot_version``, and the tarball is checked against the registry ``integrity``.
"""

import base64
import hashlib
import json
import re
import tarfile
import urllib.parse
import urllib.request
from collections.abc import Iterator
from pathlib import Path

from terminology_indexes.ingest.base import TIMEOUT, Adapter, RawSnapshot, download, make_request
from terminology_indexes.ingest.text import dedupe, squash
from terminology_indexes.model import Entry, Label

REGISTRY = "https://registry.npmjs.org/"

# "Math.pow ( base, exponent )" -> "Math.pow"; the spec writes signatures with inner spaces.
_SIGNATURE = re.compile(r"\s+\(\s.*\)$|\s+\(\s*\)$")


def read_package(path: Path) -> tuple[str, bytes]:
    """Return ``(version, biblio.json bytes)`` from the npm tarball."""
    with tarfile.open(path, "r:gz") as tar:
        package = json.load(tar.extractfile("package/package.json"))
        return package["version"], tar.extractfile("package/biblio.json").read()


def check_integrity(path: Path, integrity: str) -> None:
    algo, _, expected = integrity.partition("-")
    with path.open("rb") as f:
        actual = base64.b64encode(hashlib.file_digest(f, algo).digest()).decode()
    if actual != expected:
        raise ValueError(f"{path}: {algo} {actual} does not match the registry integrity {expected}")


class Ecma262(Adapter):
    def fetch(self, raw_dir: Path) -> RawSnapshot:
        package, version = self.source.fetch["url"], self.source.fetch.get("version", "latest")
        meta_url = REGISTRY + urllib.parse.quote(package, safe="@") + "/" + version
        with urllib.request.urlopen(make_request(meta_url), timeout=TIMEOUT) as r:
            meta = json.load(r)
        path = raw_dir / self.source.id / f"ecma262-biblio-{meta['version']}.tgz"
        download(meta["dist"]["tarball"], path)
        check_integrity(path, meta["dist"]["integrity"])
        return self.snapshot(path)

    def snapshot(self, path: Path) -> RawSnapshot:
        version, data = read_package(path)
        sha = hashlib.sha256(data).hexdigest()
        return RawSnapshot(path=path, sha256=sha, snapshot_version=f"{version}+{sha[:12]}")

    def parse(self, snapshot: RawSnapshot) -> Iterator[Entry]:
        _, data = read_package(snapshot.path)
        biblio = json.loads(data)
        base = biblio["location"]
        for e in biblio["entries"]:
            if e["type"] == "term":
                # Several terms can share the anchor of their clause, so the term is the id.
                term = squash(e["term"])
                variants = [Label(squash(v), "en", "alt") for v in e.get("variants") or []]
                yield Entry(
                    external_id=f"term:{term}",
                    url=base + "#" + (e.get("id") or e["refId"]),
                    title=term,
                    kind="term",
                    lang="en",
                    extra={"type": "term"},
                    labels=dedupe([Label(term, "en", "pref"), *variants]),
                )
            elif e["type"] == "clause" and e.get("title"):
                title = squash(e["title"])
                yield Entry(
                    external_id=e["id"],
                    url=base + "#" + e["id"],
                    title=title,
                    kind=self.source.kind_default,
                    lang="en",
                    extra={"type": "clause", "number": e.get("number") or None},
                    labels=[Label(_SIGNATURE.sub("", title), "en", "pref")],
                )

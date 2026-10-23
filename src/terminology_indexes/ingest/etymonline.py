"""Etymonline as a catalog "lemma -> URL" from its word sitemap; no content.

``/sitemap.xml`` redirects to ``/sitemaps/words-en.xml``: one ``<loc>`` per
``/word/<lemma>`` page (47 000 of them). Titles, affixes (``-emia``) and PIE
roots (``*kwo-``) are taken as they are. The ``lastmod`` dates change without a
new word, so the hash is of the lemmas.
"""

import hashlib
import urllib.parse
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from pathlib import Path

from terminology_indexes.ingest.base import Adapter, RawSnapshot, download
from terminology_indexes.ingest.html_page import RobotsDenied, robots_allowed
from terminology_indexes.model import Entry, Label

LOC = "{http://www.sitemaps.org/schemas/sitemap/0.9}loc"
WORD = "https://www.etymonline.com/word/"


def lemmas(path: Path) -> list[tuple[str, str]]:
    """``(lemma, url)`` of every word page, sorted."""
    found = set()
    for _, el in ET.iterparse(path):
        if el.tag == LOC and el.text and el.text.startswith(WORD):
            slug = el.text.strip()[len(WORD) :]
            if slug and "/" not in slug:
                found.add((urllib.parse.unquote(slug), el.text.strip()))
        el.clear()
    return sorted(found)


class Etymonline(Adapter):
    def fetch(self, raw_dir: Path) -> RawSnapshot:
        url = self.source.fetch["url"]
        if not robots_allowed(url) or not robots_allowed(WORD):
            raise RobotsDenied(f"{url} or {WORD} is disallowed by robots.txt")
        path = raw_dir / self.source.id / "words.xml"
        download(url, path, headers={"Accept": "application/xml"})
        return self.snapshot(path)

    def snapshot(self, path: Path) -> RawSnapshot:
        digest = hashlib.sha256()
        for lemma, url in lemmas(path):
            digest.update(f"{lemma}\t{url}\n".encode())
        sha = digest.hexdigest()
        return RawSnapshot(path=path, sha256=sha, snapshot_version=sha[:12])

    def parse(self, snapshot: RawSnapshot) -> Iterator[Entry]:
        for lemma, url in lemmas(snapshot.path):
            yield Entry(
                external_id=lemma,
                url=url,
                title=lemma,
                kind=self.source.kind_default,
                lang="en",
                labels=[Label(lemma, "en", "pref")],
            )

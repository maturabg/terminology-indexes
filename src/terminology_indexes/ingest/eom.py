"""Encyclopedia of Mathematics: article titles through ``list=allpages``.

Only titles: the articles are mixed rights (the originals are © Springer).
Redirects are left out, they have no article of their own.
"""

from collections.abc import Iterator
from pathlib import Path

from terminology_indexes.ingest.base import Adapter, RawSnapshot
from terminology_indexes.ingest.mediawiki import (
    MAX_LIMIT,
    list_pages,
    page_url,
    pages_snapshot,
    read_pages,
    write_pages,
)
from terminology_indexes.ingest.text import heading_labels
from terminology_indexes.model import Entry

WIKI_URL = "https://encyclopediaofmath.org/wiki/"
PAGES = "pages.jsonl"


class Eom(Adapter):
    def fetch(self, raw_dir: Path) -> RawSnapshot:
        root = raw_dir / self.source.id
        rps = (self.source.raw.get("rate_limit") or {}).get("rps", 1)
        params = {"list": "allpages", "apnamespace": "0", "apfilterredir": "nonredirects", "aplimit": str(MAX_LIMIT)}
        write_pages(root / PAGES, list_pages(self.source.fetch["url"], params, rps=rps))
        return self.snapshot(root)

    def snapshot(self, root: Path) -> RawSnapshot:
        return pages_snapshot([root / PAGES], root)

    def parse(self, snapshot: RawSnapshot) -> Iterator[Entry]:
        for page in read_pages(snapshot.path / PAGES):
            title = page["title"]
            yield Entry(
                external_id=str(page["pageid"]),
                url=page_url(WIKI_URL, title),
                title=title,
                kind=self.source.kind_default,
                lang="en",
                labels=heading_labels(title),
            )

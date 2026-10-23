"""Wiktionary EN and BG: page titles only, from the lemma category of each wiki.

The ``all-titles-in-ns0`` dumps hold every language (9 M titles on enwiktionary,
800 k on bgwiktionary, mostly inflected forms); the lemma categories are the
English and Bulgarian entries proper. Whether a page still has its language
section is the live ``check`` (iteration 7).
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
from terminology_indexes.model import Entry, Label

# Titles the wiki cannot hold ("[", " ") live under this prefix with another display title.
UNSUPPORTED = "Unsupported titles/"


class Wiktionary(Adapter):
    def fetch(self, raw_dir: Path) -> RawSnapshot:
        root = raw_dir / self.source.id
        rps = (self.source.raw.get("rate_limit") or {}).get("rps", 1)
        for wiki in self.source.fetch["wikis"]:
            params = {
                "list": "categorymembers",
                "cmtitle": wiki["category"],
                "cmnamespace": "0",
                "cmtype": "page",
                "cmprop": "ids|title",
                "cmlimit": str(MAX_LIMIT),
            }
            write_pages(root / f"{wiki['lang']}.jsonl", list_pages(wiki["api"], params, rps=rps))
        return self.snapshot(root)

    def snapshot(self, root: Path) -> RawSnapshot:
        return pages_snapshot([root / f"{w['lang']}.jsonl" for w in self.source.fetch["wikis"]], root)

    def parse(self, snapshot: RawSnapshot) -> Iterator[Entry]:
        for wiki in self.source.fetch["wikis"]:
            lang, anchor = wiki["lang"], wiki.get("anchor")
            for page in read_pages(snapshot.path / f"{lang}.jsonl"):
                title = page["title"]
                if title.startswith(UNSUPPORTED):
                    continue
                url = page_url(wiki["url"], title)
                yield Entry(
                    external_id=f"{lang}:{title}",
                    url=f"{url}#{anchor}" if anchor else url,
                    title=title,
                    kind=self.source.kind_default,
                    lang=lang,
                    extra={"pageid": page["pageid"]},
                    labels=[Label(title, lang, "pref")],
                )

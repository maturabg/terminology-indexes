"""PostgreSQL Glossary: ``<dt id="GLOSSARY-…">`` on one HTML page."""

from collections.abc import Iterator

from terminology_indexes.ingest.base import RawSnapshot
from terminology_indexes.ingest.html_page import HtmlPage, attr
from terminology_indexes.ingest.text import dedupe, heading_labels, squash, title_variants
from terminology_indexes.model import Entry, Label

# Fetch is pinned (see the yaml), public links point to /current/ (docs/decisions.md).
PUBLIC_URL = "https://www.postgresql.org/docs/current/glossary.html#"
GLOSSARY_HREF = "glossary.html#"


class PostgresqlGlossary(HtmlPage):
    def parse(self, snapshot: RawSnapshot) -> Iterator[Entry]:
        entries: dict[str, Entry] = {}
        redirects: list[tuple[str, str]] = []
        for dt in self.soup(snapshot).select("div.glosslist dl > dt"):
            title = squash(dt.get_text())
            dd = dt.find_next_sibling("dd")
            anchor = attr(dt, "id")
            if not anchor:
                # "Database server — See Instance": no anchor of its own, a label of the target.
                see = dd and dd.find("a", class_="glosssee", href=True)
                if see and (href := attr(see, "href")).startswith(GLOSSARY_HREF):
                    redirects.append((href.removeprefix(GLOSSARY_HREF), title))
                continue
            p = dd and dd.find("p")
            entries[anchor] = Entry(
                external_id=anchor,
                url=PUBLIC_URL + anchor,
                title=title,
                kind=self.source.kind_default,
                lang="en",
                snippet=squash(p.get_text()) if p else None,
                labels=heading_labels(title),
            )
        for target, title in redirects:
            if entry := entries.get(target):
                entry.labels = dedupe([*entry.labels, *(Label(v, "en", "redirect") for v in title_variants(title))])
        yield from entries.values()

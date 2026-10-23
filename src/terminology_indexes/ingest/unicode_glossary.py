"""Unicode Glossary: ``<p id="…">`` whose term links to its own anchor.

Links are explicitly permitted, the text is not (``snippet_policy: none``); the
definition is read only for "Acronym for …" labels.
"""

import re
from collections.abc import Iterator

from terminology_indexes.ingest.base import RawSnapshot
from terminology_indexes.ingest.html_page import HtmlPage, attr
from terminology_indexes.ingest.text import dedupe, heading_labels, squash
from terminology_indexes.model import Entry, Label

BASE = "https://www.unicode.org/glossary/#"

_EXPANSION = re.compile(r"\.?\s*(?:Acronym|Abbreviation) for ([^.(]+?)\s*[.(]")
# "Backus-Naur Form, a formal meta-syntax …": the expansion ends before the lowercase aside.
_ASIDE = re.compile(r",\s+(?!and\b|or\b)[a-z].*")


class UnicodeGlossary(HtmlPage):
    def parse(self, snapshot: RawSnapshot) -> Iterator[Entry]:
        for p in self.soup(snapshot).find_all("p", id=True):
            # The letter headings ("A", "P-Q") have ids too, but no self-link.
            anchor = attr(p, "id")
            if not (a := p.find("a", href="#" + anchor)):
                continue
            title = squash(a.get_text())
            labels = heading_labels(title)
            rest = squash(p.get_text()).removeprefix(title)
            if m := _EXPANSION.match(rest):
                labels = dedupe([*labels, Label(_ASIDE.sub("", m[1]), "en", "alt")])
            yield Entry(
                external_id=anchor,
                url=BASE + anchor,
                title=title,
                kind=self.source.kind_default,
                lang="en",
                labels=labels,
            )

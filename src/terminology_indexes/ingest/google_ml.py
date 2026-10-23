"""Google Machine Learning Glossary: ``<h2 class="hide-from-toc" id="…">`` on one page."""

from collections.abc import Iterator

from bs4 import Tag

from terminology_indexes.ingest.base import RawSnapshot
from terminology_indexes.ingest.html_page import HtmlPage, attr
from terminology_indexes.ingest.text import heading_labels, squash
from terminology_indexes.model import Entry

BASE = "https://developers.google.com/machine-learning/glossary#"


def definition(head: Tag) -> str | None:
    """The first paragraph after the heading (``head`` is the h2 or its icon container).

    The heading sits inside a <p> with the topic icons; the definition is either the
    rest of that <p> or the next <p>.
    """
    if text := squash("".join(s.get_text() for s in head.next_siblings)):
        return text
    for el in head.find_all_next(["h2", "p"]):
        if el.name == "h2":
            return None
        if not el.find("h2") and (text := squash(el.get_text())):
            return text
    return None


class GoogleMl(HtmlPage):
    def parse(self, snapshot: RawSnapshot) -> Iterator[Entry]:
        # The letter headings are h2.glossary; terms are h2.hide-from-toc; "Page Summary" is .no-link.
        for h2 in self.soup(snapshot).select("h2.hide-from-toc[id]:not(.no-link)"):
            anchor, title = attr(h2, "id"), squash(h2.get_text())
            icons = h2.find_next_sibling("div", class_="glossary-icon-container")
            tags = [squash(attr(t, "title")) for t in icons.find_all("div", title=True)] if icons else []
            snippet = definition(icons or h2)
            yield Entry(
                external_id=anchor,
                url=BASE + anchor,
                title=title,
                kind=self.source.kind_default,
                lang="en",
                snippet=snippet,
                extra={"tags": tags} if tags else None,
                labels=heading_labels(title),
            )

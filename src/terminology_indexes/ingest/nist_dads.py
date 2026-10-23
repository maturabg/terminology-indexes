"""NIST DADS from its alphabetical index: the front page lists every term.

``<dt><a href="HTML/abtree.html">(a,b)-tree</a>`` is a term; ``<dt>ADT: see <a
href="HTML/abstractDataType.html">abstract data type</a>`` is another name of
one. Definitions live on the 1 100+ term pages and are not fetched: at the
polite rate that would be over an hour per refresh, so there is no snippet.
"""

import re
from collections.abc import Iterator

from bs4 import BeautifulSoup

from terminology_indexes.ingest.base import RawSnapshot
from terminology_indexes.ingest.html_page import HtmlPage
from terminology_indexes.ingest.text import dedupe, squash, title_variants
from terminology_indexes.model import Entry, Label

BASE = "https://xlinux.nist.gov/dads/"

# The <dt> elements are never closed: read the index line by line.
_DT = re.compile(r"<dt>(.*)", re.IGNORECASE)
_HREF = re.compile(r"HTML/([\w.-]+)\.html")
_SEE = re.compile(r"(.+?):\s*see\s*$")


def fragment_text(markup: str) -> str:
    """``B<sub>k</sub> tree`` -> ``Bk tree``."""
    return squash(BeautifulSoup(markup, "html.parser").get_text())


class NistDads(HtmlPage):
    def parse(self, snapshot: RawSnapshot) -> Iterator[Entry]:
        direct: dict[str, list[str]] = {}  # page -> names listed with a link of their own
        see: dict[str, list[str]] = {}  # page -> "X: see ..." names
        for line in snapshot.path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not (m := _DT.match(line.strip())):
                continue
            dt = BeautifulSoup(m[1], "html.parser")
            link = next((a for a in dt.find_all("a", href=True) if _HREF.fullmatch(str(a["href"]))), None)
            if link is None:
                continue
            page = _HREF.fullmatch(str(link["href"]))[1]
            lead = fragment_text("".join(str(n) for n in dt.contents[: dt.contents.index(link)]))
            if not lead:
                direct.setdefault(page, []).append(fragment_text(link.decode_contents()))
            elif m := _SEE.match(lead):
                see.setdefault(page, []).append(m[1])
        for page, names in sorted(direct.items()):
            first, *rest = title_variants(names[0])
            labels = [Label(first, "en", "pref"), *(Label(v, "en", "alt") for v in rest)]
            labels += [Label(v, "en", "alt") for name in names[1:] for v in title_variants(name)]
            labels += [Label(v, "en", "redirect") for name in see.get(page, []) for v in title_variants(name)]
            yield Entry(
                external_id=page,
                url=f"{BASE}HTML/{page}.html",
                title=names[0],
                kind=self.source.kind_default,
                lang="en",
                labels=dedupe(labels),
            )

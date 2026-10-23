"""W3C specifications as whole documents; their terms come from webref.

The API has no search, so the first ``search`` reads the list of all ~1 700
specifications (two requests) and matches titles and shortnames locally. The
details of each hit (``/specifications/<shortname>``) give the description and
whether the spec is retired; retired specs are not offered.
"""

import re
import urllib.parse

from bs4 import BeautifulSoup

from terminology_indexes.contract import Candidate, CheckResult, LinkRecord
from terminology_indexes.normalize import normalize_term, term_key
from terminology_indexes.providers.live import LiveProvider, short

TR = "https://www.w3.org/TR/"
PAGE = 1000
# "CSS Grid Layout Module Level 1" is also "CSS Grid Layout"
_LEVEL = re.compile(r"(\s+module)?(\s+(level|version)\s+[\d.]+|\s+[\d.]+)?$", re.IGNORECASE)
_BRACKETS = re.compile(r"\s*\(([^()]+)\)")
_WORD = re.compile(r"\w+")


def aliases(title: str) -> set[str]:
    """``label_key``s of the other names in a title: without the level, without
    the bracketed part, and the bracketed part itself ("Web Content Accessibility
    Guidelines (WCAG) 2.2" -> "Web Content Accessibility Guidelines", "WCAG")."""
    base = _LEVEL.sub("", title)
    return {term_key(base), term_key(_BRACKETS.sub("", base))} | {term_key(b) for b in _BRACKETS.findall(base)}


def words(text: str) -> set[str]:
    return set(_WORD.findall(normalize_term(text)))


def level(title: str) -> float:
    m = re.search(r"([\d.]+)$", title)
    try:
        return float(m[1]) if m else 0.0
    except ValueError:
        return 0.0


class W3c(LiveProvider):
    id = "w3c"
    api = "https://api.w3.org/"
    rps = 10

    def __init__(self, env) -> None:
        super().__init__(env)
        self._catalog: list[tuple[str, str]] | None = None  # (shortname, title)

    def catalog(self) -> list[tuple[str, str]]:
        if self._catalog is None:
            specs, page, pages = [], 1, 1
            while page <= pages:
                data = self.http.get_json(f"{self.api}specifications", {"items": str(PAGE), "page": str(page)})
                pages = data["pages"]
                specs += [
                    (link["href"].rstrip("/").rsplit("/", 1)[1], link["title"])
                    for link in data["_links"]["specifications"]
                ]
                page += 1
            self._catalog = specs
        return self._catalog

    def spec(self, shortname: str) -> dict:
        return self.http.get_json(f"{self.api}specifications/{urllib.parse.quote(shortname)}")

    def search(self, query: str, *, lang: str | None = None, limit: int = 5) -> list[Candidate]:
        if lang not in (None, "en"):
            return []
        key, query_words = term_key(query), words(query)
        if not query_words:
            return []
        ranked = []
        for shortname, title in self.catalog():
            if key in (term_key(title), term_key(shortname)):
                match = "exact"
            elif key in aliases(title):
                match = "alias"
            elif query_words <= words(title):
                match = "fts"
            else:
                continue
            # higher levels first, then shorter titles
            ranked.append((["exact", "alias", "fts"].index(match), -level(title), len(title), shortname, title, match))
        hits = []
        # each hit costs a request for its details; retired specs are skipped
        for *_, shortname, title, match in sorted(ranked)[: 3 * limit]:
            spec = self.spec(shortname)
            if spec.get("_links", {}).get("latest-version", {}).get("title") == "Retired":
                continue
            description = BeautifulSoup(spec.get("description") or "", "html.parser").get_text(" ")
            hits.append(
                self.candidate(
                    external_id=shortname,
                    url=spec.get("shortlink") or f"{TR}{shortname}/",
                    title=title,
                    kind="document",
                    matched_label=title,
                    match=match,
                    snippet=short(description),
                )
            )
            if len(hits) == limit:
                break
        return hits

    def _check(self, link: LinkRecord) -> CheckResult:
        spec = self.spec(link.external_id)  # 404 -> dead; a renamed shortname redirects
        shortname = spec.get("shortname", link.external_id)
        url = spec.get("shortlink") or f"{TR}{shortname}/"
        if url != link.url:
            renamed = f"{link.external_id} is now {shortname}" if shortname != link.external_id else "url changed"
            return CheckResult("moved", new_url=url, reason=renamed)
        retired = spec.get("_links", {}).get("latest-version", {}).get("title") == "Retired"
        return CheckResult("ok", reason="retired" if retired else "")

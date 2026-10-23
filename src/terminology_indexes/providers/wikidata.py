"""Wikidata items with their Wikipedia article: ``wbsearchentities``, then the sitelinks.

``external_id`` is the QID, the URL is the article on the Wikipedia of the query's
language (EN otherwise). Items without an EN or BG article are left out: the link
is to an article. The snippet is the Wikidata description (CC0), never article text.
"""

import urllib.parse

from terminology_indexes.contract import Candidate, CheckResult, LinkRecord
from terminology_indexes.normalize import term_key
from terminology_indexes.providers.live import LiveProvider, short

SITES = {"en": "enwiki", "bg": "bgwiki"}
WIKIDATA_URL = "https://www.wikidata.org/wiki/"
# Not concepts: descriptions of Wikimedia's own pages
SKIP_DESCRIPTIONS = ("wikimedia disambiguation page", "уикимедия пояснителна страница", "wikimedia category")


def site_of(url: str) -> str | None:
    """``enwiki`` / ``bgwiki`` for an article URL."""
    host = urllib.parse.urlsplit(url).netloc
    return next((site for lang, site in SITES.items() if host == f"{lang}.wikipedia.org"), None)


def same_url(a: str, b: str) -> bool:
    """MediaWiki reads ``_`` and a space in a title as the same."""
    return urllib.parse.unquote(a).replace(" ", "_") == urllib.parse.unquote(b).replace(" ", "_")


class Wikidata(LiveProvider):
    id = "wikidata"
    api = "https://www.wikidata.org/w/api.php"
    rps = 1

    def _entities(self, ids: list[str], *, languages: str = "en|bg") -> dict[str, dict]:
        data = self.http.get_json(
            self.api,
            {
                "action": "wbgetentities",
                "ids": "|".join(ids),
                "props": "labels|descriptions|sitelinks/urls",
                "languages": languages,
                "sitefilter": "|".join(SITES.values()),
                "format": "json",
            },
        )
        if "error" in data:
            raise ValueError(f"wbgetentities: {data['error'].get('info')}")
        return data["entities"]

    def search(self, query: str, *, lang: str | None = None, limit: int = 5) -> list[Candidate]:
        lang = lang if lang in SITES else "en"
        found = self.http.get_json(
            self.api,
            {
                "action": "wbsearchentities",
                "search": query,
                "language": lang,
                "uselang": lang,
                "type": "item",
                "limit": str(min(50, max(10, 2 * limit))),
                "format": "json",
            },
        ).get("search", [])
        if not found:
            return []
        entities = self._entities([f["id"] for f in found])
        key = term_key(query)
        hits = []
        for f in found:
            item = entities.get(f["id"], {})
            sitelinks = item.get("sitelinks", {})
            site = SITES[lang] if SITES[lang] in sitelinks else next(iter(sitelinks), None)
            description = (item.get("descriptions", {}).get(lang) or {}).get("value") or f.get("description")
            if site is None or (description or "").casefold() in SKIP_DESCRIPTIONS:
                continue
            matched = f.get("match", {}).get("text") or f.get("label") or f["id"]
            if term_key(matched) != key:
                match = "fts"
            else:
                match = "exact" if f.get("match", {}).get("type") == "label" else "alias"
            label = (item.get("labels", {}).get(lang) or {}).get("value") or f.get("label") or f["id"]
            hits.append(
                self.candidate(
                    external_id=f["id"],
                    url=sitelinks[site]["url"],
                    title=label,
                    kind="concept",
                    matched_label=matched,
                    match=match,
                    snippet=short(description),
                )
            )
        # wbsearchentities ranks by its own relevance; keep that order within a match type
        hits.sort(key=lambda c: ["exact", "alias", "fts"].index(c.match))
        return hits[:limit]

    def _check(self, link: LinkRecord) -> CheckResult:
        item = self._entities([link.external_id], languages="en").get(link.external_id, {})
        if "missing" in item:
            return CheckResult("dead", reason=f"{link.external_id} deleted")
        merged = item.get("redirects", {}).get("to")
        note = f"{link.external_id} merged into {merged}" if merged else ""
        sitelinks = item.get("sitelinks", {})
        if link.url.startswith(WIKIDATA_URL):
            return CheckResult("moved", new_url=WIKIDATA_URL + merged, reason=note) if merged else CheckResult("ok")
        site = site_of(link.url)
        current = sitelinks.get(site) if site else None
        if current is None:
            current = next(iter(sitelinks.values()), None)
            if current is None:
                return CheckResult("dead", reason=f"{item.get('id', link.external_id)} has no EN or BG article")
            note = note or f"no {site or 'such'} article"
        if same_url(current["url"], link.url):
            return CheckResult("ok", reason=note)  # a merged QID with the same article is still a good link
        return CheckResult("moved", new_url=current["url"], reason=note or "article renamed")

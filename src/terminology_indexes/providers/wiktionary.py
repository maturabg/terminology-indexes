"""Wiktionary: ``search`` from the index (lemma titles), ``check`` live by ``pageid``.

A page in the lemma category can still lose its language section, be moved or be
deleted; ``action=parse&prop=tocdata`` tells all three in one request.
"""

import json
import urllib.error
import urllib.parse

from terminology_indexes.contract import CheckResult, LinkRecord
from terminology_indexes.ingest.mediawiki import page_url
from terminology_indexes.providers.index import IndexProvider
from terminology_indexes.providers.live import DailyLimitReached, Http, status_result

API = "https://{lang}.wiktionary.org/w/api.php"  # = ``live.api`` in wiktionary.yaml
RPS = 2  # = ``rate_limit.rps``
# lang -> (page URL, language section; the EN URL points to it)
WIKIS = {"en": ("https://en.wiktionary.org/wiki/", "English"), "bg": ("https://bg.wiktionary.org/wiki/", "Български")}
GONE = {"nosuchpageid", "missingtitle"}


class WiktionaryProvider(IndexProvider):
    live = False  # search reads the index; only check goes to the API

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.http = Http(RPS)

    def _pageid(self, external_id: str) -> int | None:
        row = self.conn.execute(
            "SELECT extra FROM entries WHERE source = ? AND external_id = ?", (self.id, external_id)
        ).fetchone()
        return json.loads(row[0]).get("pageid") if row and row[0] else None

    def check(self, link: LinkRecord) -> CheckResult:
        lang, _, title = link.external_id.partition(":")
        if lang not in WIKIS or not title:
            return CheckResult("unknown", reason=f"not a wiktionary id: {link.external_id!r}")
        base, section = WIKIS[lang]
        # A page that left the lemma category is not in the index; look it up by title then.
        pageid = self._pageid(link.external_id)
        params = {"action": "parse", "prop": "tocdata", "redirects": "1", "format": "json", "formatversion": "2"}
        params |= {"pageid": str(pageid)} if pageid else {"page": title}
        try:
            data = self.http.get_json(API.format(lang=lang), params)
        except urllib.error.HTTPError as e:
            return status_result(e.code, e.headers.get("Location"), link.url)
        except (OSError, DailyLimitReached, ValueError) as e:
            return CheckResult("unknown", reason=f"{type(e).__name__}: {e}")
        if "error" in data:
            if data["error"].get("code") in GONE:
                return CheckResult("dead", reason=f"page {pageid or title!r} does not exist")
            return CheckResult("unknown", reason=data["error"].get("info", ""))
        page = data["parse"]
        sections = [s["line"] for s in page.get("tocdata", {}).get("sections", []) if s.get("tocLevel") == 1]
        if section not in sections:
            return CheckResult("dead", reason=f"{page['title']!r} has no {section} section")
        url = page_url(base, page["title"]) + (f"#{section}" if lang == "en" else "")
        if urllib.parse.unquote(url) == urllib.parse.unquote(link.url):
            return CheckResult("ok")
        reason = "page moved" if page["title"] != title else "url changed"
        return CheckResult("moved", new_url=url, reason=reason)

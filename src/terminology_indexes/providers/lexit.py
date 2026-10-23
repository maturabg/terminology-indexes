"""ЛЕКСИТ, the dictionary portal of the Institute for Bulgarian Language: live HTML.

There is no API and no permalink of a sense: the link is the portal's result
page for a word, ``/dictionary_portal/lang/bg/<word>``. A page with a headword
(``Основна форма``) or a block ``Резултати от: <dictionary>`` is a hit. All rights
reserved: only the link is kept, never text. The rate limit is low (0.2 rps,
500 a day), so only Cyrillic queries are sent.
"""

import re
import unicodedata
import urllib.parse

from bs4 import BeautifulSoup

from terminology_indexes.contract import Candidate, CheckResult, LinkRecord
from terminology_indexes.normalize import term_key
from terminology_indexes.providers.live import LiveProvider

PAGE = "https://ibl.bas.bg/dictionary_portal/lang/bg/"
_CYRILLIC = re.compile(r"[а-яА-ЯѐЀ-ӿ]")
_HEADWORD = re.compile(r"Основна форма:\s*(.+)")
_RESULTS = re.compile(r"Резултати от:\s*(.+)")


def page_url(word: str) -> str:
    return PAGE + urllib.parse.quote(word)


def strip_stress(text: str) -> str:
    """``компю̀тър`` -> ``компютър`` (the portal marks stress with combining accents)."""
    return unicodedata.normalize("NFC", "".join(c for c in unicodedata.normalize("NFD", text) if c not in "̀́"))


def results(html: bytes | str) -> tuple[str | None, list[str]]:
    """The headword and the dictionaries with a result on a portal page."""
    soup = BeautifulSoup(html, "html.parser")
    headword = None
    for h3 in soup.find_all("h3"):
        if small := h3.find("small"):
            small.extract()  # the part of speech
        if m := _HEADWORD.match(h3.get_text(" ", strip=True)):
            headword = strip_stress(m[1]).strip()
            break
    dictionaries = [
        m[1].strip(" :") for h4 in soup.find_all("h4") if (m := _RESULTS.match(h4.get_text(" ", strip=True)))
    ]
    return headword, dictionaries


class Lexit(LiveProvider):
    id = "lexit"
    api = "https://ibl.bas.bg/dictionary_portal/"
    rps = 0.2
    daily = 500

    def search(self, query: str, *, lang: str | None = None, limit: int = 5) -> list[Candidate]:
        word = " ".join(query.split())
        if lang not in (None, "bg") or not _CYRILLIC.search(word):
            return []
        url = page_url(word)
        headword, dictionaries = results(self.http.get(url, headers={"Accept": "text/html"}))
        if not dictionaries and headword is None:
            return []
        title = headword or word
        if term_key(title) != term_key(word):
            url = page_url(title)  # a form of the word: link the headword's page
        return [
            self.candidate(
                external_id=title,
                url=url,
                title=f"{title} ({', '.join(dictionaries)})" if dictionaries else title,
                kind="term",
                matched_label=title,
                match="exact" if term_key(title) == term_key(word) else "alias",
                snippet=None,
            )
        ]

    def _check(self, link: LinkRecord) -> CheckResult:
        url = page_url(link.external_id)
        headword, dictionaries = results(self.http.get(url, headers={"Accept": "text/html"}))
        if not dictionaries and headword is None:
            return CheckResult("dead", reason="no result on the portal")
        if url != link.url:
            return CheckResult("moved", new_url=url, reason="url changed")
        return CheckResult("ok")

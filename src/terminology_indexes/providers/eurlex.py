"""EUR-Lex acts through Cellar: SPARQL full text over the titles, ``check`` by CELEX.

Only legislation (CELEX sector 3) of the three main types: regulations (R),
directives (L) and decisions (D), without corrigenda. An act whose short title
in brackets is the query ("General Data Protection Regulation") is ``exact``;
the rest are ``fts`` hits, acts in force and of the Parliament and Council first.
The SOAP web service needs a registration and is not used.
"""

import re
import urllib.parse

from terminology_indexes.contract import Candidate, CheckResult, LinkRecord
from terminology_indexes.normalize import term_key
from terminology_indexes.providers.live import LiveProvider, status_result

CELLAR = "https://publications.europa.eu/resource/celex/"
EURLEX = "https://eur-lex.europa.eu/legal-content/{lang}/TXT/?uri=CELEX:{celex}"
LANGS = {"en": "ENG", "bg": "BUL"}
SPARQL_JSON = "application/sparql-results+json"
POOL = 100  # titles SPARQL returns, ranked here
QUERY = """
PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>
SELECT ?celex ?title ?force ?date WHERE {
  ?work cdm:resource_legal_id_celex ?celex .
  ?expr cdm:expression_belongs_to_work ?work ;
        cdm:expression_uses_language <http://publications.europa.eu/resource/authority/language/%(lang)s> ;
        cdm:expression_title ?title .
  ?title bif:contains '%(phrase)s' .
  FILTER (REGEX(STR(?celex), "^3[0-9]{4}[RLD][0-9]+$"))
  OPTIONAL { ?work cdm:resource_legal_in-force ?force }
  OPTIONAL { ?work cdm:work_date_document ?date }
} ORDER BY DESC(?force) DESC(?date) LIMIT %(pool)d
"""
_BRACKETS = re.compile(r"\(([^()]+)\)")
# Acts of the legislator itself, not implementing or delegated ones
_BASIC = ("of the European Parliament and of the Council", "на Европейския парламент и на Съвета")
_PHRASE_WORDS = re.compile(r"\w+")


def phrase(query: str) -> str | None:
    """A ``bif:contains`` phrase of the query's words; quotes and operators cannot get in."""
    found = _PHRASE_WORDS.findall(query)
    return f'"{" ".join(found)}"' if found else None


class Eurlex(LiveProvider):
    id = "eurlex"
    api = "https://publications.europa.eu/webapi/rdf/sparql"
    rps = 1

    def search(self, query: str, *, lang: str | None = None, limit: int = 5) -> list[Candidate]:
        lang = lang if lang in LANGS else "en"
        if not (text := phrase(query)):
            return []
        sparql = QUERY % {"lang": LANGS[lang], "phrase": text, "pool": POOL}
        rows = self.http.get_json(self.api, {"query": sparql}, accept=SPARQL_JSON)
        key = term_key(query)
        ranked = []
        for row in rows["results"]["bindings"]:
            celex, title = row["celex"]["value"], " ".join(row["title"]["value"].split())
            short_titles = [s for s in _BRACKETS.findall(title) if term_key(s) == key]
            in_force = row.get("force", {}).get("value") in ("1", "true")
            basic = any(b in title for b in _BASIC)
            ranked.append((not short_titles, not in_force, not basic, len(title), celex, title, short_titles))
        hits, seen = [], set()
        for *_, celex, title, short_titles in sorted(ranked):
            if celex in seen:
                continue
            seen.add(celex)
            hits.append(
                self.candidate(
                    external_id=celex,
                    url=EURLEX.format(lang=lang.upper(), celex=celex),
                    title=title,
                    kind="document",
                    matched_label=short_titles[0] if short_titles else query,
                    match="exact" if short_titles else "fts",
                    snippet=None,
                )
            )
            if len(hits) == limit:
                break
        return hits

    def _check(self, link: LinkRecord) -> CheckResult:
        # Cellar answers 303 (to the work) for a CELEX it knows, 404 otherwise.
        code, location = self.http.status(CELLAR + urllib.parse.quote(link.external_id))
        if code == 303:
            return CheckResult("ok")
        return status_result(code, location, link.url)

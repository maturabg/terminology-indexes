"""Live providers against canned API answers: no network."""

import email.message
import json
import shutil
import threading
import time
import urllib.error
from pathlib import Path

import pytest
from conftest import ETYMONLINE, ROOT, load_source, parse_fixture

from terminology_indexes.build import build_shard, combine
from terminology_indexes.contract import CheckResult, LinkRecord
from terminology_indexes.ingest import get_adapter
from terminology_indexes.model import load_registry
from terminology_indexes.providers import INDEX_PROVIDERS, LIVE_PROVIDERS, Registry, _load, load_providers
from terminology_indexes.providers.eurlex import Eurlex, phrase
from terminology_indexes.providers.lexit import Lexit, results
from terminology_indexes.providers.live import DailyLimitReached, Http, status_result
from terminology_indexes.providers.w3c import W3c
from terminology_indexes.providers.wikidata import Wikidata
from terminology_indexes.providers.wiktionary import WiktionaryProvider


def http_error(code: int, location: str | None = None) -> urllib.error.HTTPError:
    headers = email.message.Message()
    if location:
        headers["Location"] = location
    return urllib.error.HTTPError("https://example.org/", code, "", headers, None)


class FakeHttp:
    """``handler(url, params)`` answers ``get`` / ``get_json``; ``statuses[url]`` answers ``status``."""

    def __init__(self, handler=None, statuses=None) -> None:
        self.handler = handler
        self.statuses = statuses or {}
        self.calls: list[tuple[str, dict]] = []

    def _answer(self, url, params):
        self.calls.append((url, params or {}))
        answer = self.handler(url, params or {})
        if isinstance(answer, Exception):
            raise answer
        return answer

    def get(self, url, params=None, headers=None):
        return self._answer(url, params)

    def get_json(self, url, params=None, accept="application/json"):
        return self._answer(url, params)

    def status(self, url, *, method="HEAD"):
        self.calls.append((url, {}))
        return self.statuses[url]


def live(cls, handler=None, statuses=None):
    provider = cls({})
    provider.http = FakeHttp(handler, statuses)
    return provider


# --- registry ---------------------------------------------------------------


def test_live_providers_match_the_registry() -> None:
    registry = load_registry(ROOT / "sources")
    live_sources = {sid for sid, s in registry.items() if s.mode == "live" and s.status == "active"}
    assert live_sources == set(LIVE_PROVIDERS)
    for sid, target in LIVE_PROVIDERS.items():
        cls, raw = _load(target), registry[sid].raw
        assert cls.id == sid
        assert cls.api == raw["live"]["api"]
        assert cls.rps == raw["rate_limit"]["rps"]
        assert cls.daily == raw["rate_limit"]["daily"]
        assert cls.secret_env == raw["live"]["secret"]
    for sid in INDEX_PROVIDERS:
        assert registry[sid].mode == "index" and registry[sid].raw.get("live")


def test_wiktionary_constants_match_the_registry() -> None:
    from terminology_indexes.providers import wiktionary

    raw = load_source("wiktionary").raw
    assert wiktionary.API == raw["live"]["api"]
    assert wiktionary.RPS == raw["rate_limit"]["rps"]
    for wiki in raw["fetch"]["wikis"]:
        assert wiktionary.WIKIS[wiki["lang"]][0] == wiki["url"]
        if "anchor" in wiki:
            assert wiktionary.WIKIS[wiki["lang"]][1] == wiki["anchor"]


def test_load_providers_live_switch(index: Path) -> None:
    with load_providers(index, env={}) as registry:
        assert set(LIVE_PROVIDERS) <= set(registry.providers)
    with load_providers(index, env={}, live=False) as registry:
        assert list(registry.providers) == ["python_glossary"]


class Slow:
    live = True

    def __init__(self, sid: str, delay: float) -> None:
        self.id, self.delay = sid, delay
        self.threads: set[int] = set()

    def search(self, query, *, lang=None, limit=5):
        self.threads.add(threading.get_ident())
        time.sleep(self.delay)
        return [
            live(Wikidata).candidate(
                external_id=self.id,
                url="u",
                title=query,
                kind="concept",
                matched_label=query,
                match="exact",
                snippet=None,
            )
        ]

    def check(self, link):
        return CheckResult("ok")


def test_search_all_asks_live_providers_at_once() -> None:
    slow = [Slow("a", 0.3), Slow("b", 0.3), Slow("c", 0.3)]
    registry = Registry(slow)
    started = time.monotonic()
    hits = registry.search_all("x")
    assert time.monotonic() - started < 0.8
    assert [h.external_id for h in hits] == ["a", "b", "c"]  # provider order, not finishing order
    assert len({t for p in slow for t in p.threads}) == 3


# --- http -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("code", "location", "expected"),
    [
        (200, None, CheckResult("ok")),
        (302, "/tmp", CheckResult("ok")),
        (301, "/new", CheckResult("moved", "https://example.org/new", "HTTP 301")),
        (404, None, CheckResult("dead", reason="HTTP 404")),
        (410, None, CheckResult("dead", reason="HTTP 410")),
        (403, None, CheckResult("unknown", reason="HTTP 403")),
        (429, None, CheckResult("unknown", reason="HTTP 429")),
        (503, None, CheckResult("unknown", reason="HTTP 503")),
    ],
)
def test_status_result(code, location, expected) -> None:
    assert status_result(code, location, "https://example.org/old") == expected


def test_http_daily_limit_and_rate() -> None:
    http = Http(rps=20, daily=2)
    started = time.monotonic()
    http._wait()
    http._wait()
    assert time.monotonic() - started >= 0.045
    with pytest.raises(DailyLimitReached):
        http._wait()


def test_network_trouble_is_unknown() -> None:
    provider = live(Wikidata, lambda url, params: TimeoutError("timed out"))
    assert provider.check(LinkRecord("wikidata", "Q1", "https://en.wikipedia.org/wiki/X")).status == "unknown"
    provider = live(Wikidata, lambda url, params: http_error(503))
    assert provider.check(LinkRecord("wikidata", "Q1", "https://en.wikipedia.org/wiki/X")) == CheckResult(
        "unknown", reason="HTTP 503"
    )


# --- wikidata ---------------------------------------------------------------

EN = "https://en.wikipedia.org/wiki/"
BG = "https://bg.wikipedia.org/wiki/"
SEARCH = {
    "firewall": [
        {"id": "Q80998", "label": "firewall", "match": {"type": "label", "text": "firewall"}},
        {"id": "Q1", "label": "Firewall", "match": {"type": "label", "text": "Firewall"}},  # no article
        {"id": "Q2", "label": "Firewall", "match": {"type": "label", "text": "Firewall"}},  # disambiguation
        {"id": "Q3", "label": "firewall pinhole", "match": {"type": "label", "text": "firewall pinhole"}},
        {"id": "Q4", "label": "Packet filter", "match": {"type": "alias", "text": "fire-wall"}},
    ],
}
ENTITIES = {
    "Q80998": {
        "id": "Q80998",
        "labels": {"en": {"value": "firewall"}, "bg": {"value": "Защитна стена"}},
        "descriptions": {"en": {"value": "network security system"}},
        "sitelinks": {"enwiki": {"url": EN + "Firewall_(computing)"}, "bgwiki": {"url": BG + "Защитна_стена"}},
    },
    "Q1": {"id": "Q1", "labels": {"en": {"value": "Firewall"}}, "sitelinks": {}},
    "Q2": {
        "id": "Q2",
        "descriptions": {"en": {"value": "Wikimedia disambiguation page"}},
        "sitelinks": {"enwiki": {"url": EN + "Firewall"}},
    },
    "Q3": {"id": "Q3", "sitelinks": {"enwiki": {"url": EN + "Pinhole"}}},
    "Q4": {"id": "Q4", "sitelinks": {"bgwiki": {"url": BG + "Филтър"}}},
    "Q5": {
        "id": "Q80998",
        "redirects": {"from": "Q5", "to": "Q80998"},
        "sitelinks": {"enwiki": {"url": EN + "Firewall_(computing)"}},
    },
    "Q6": {"id": "Q6", "missing": ""},
}


def wikidata_api(url, params):
    if params["action"] == "wbsearchentities":
        return {"search": SEARCH.get(params["search"], [])}
    return {"entities": {q: ENTITIES[q] for q in params["ids"].split("|")}}


def test_wikidata_search() -> None:
    hits = live(Wikidata, wikidata_api).search("firewall", lang="en")
    assert [(h.external_id, h.match, h.url) for h in hits] == [
        ("Q80998", "exact", EN + "Firewall_(computing)"),
        ("Q4", "alias", BG + "Филтър"),  # no EN article: the BG one
        ("Q3", "fts", EN + "Pinhole"),
    ]
    assert hits[0].kind == "concept" and hits[0].snippet == "network security system"
    assert hits[0].snapshot_version.startswith("live:")
    bg = live(Wikidata, lambda url, p: wikidata_api(url, p | {"search": "firewall"})).search("защитна стена", lang="bg")
    assert (bg[0].title, bg[0].url) == ("Защитна стена", BG + "Защитна_стена")


@pytest.mark.parametrize(
    ("qid", "url", "expected"),
    [
        ("Q80998", EN + "Firewall_(computing)", CheckResult("ok")),
        ("Q80998", EN + "Firewall%20(computing)", CheckResult("ok")),
        ("Q80998", EN + "Firewall", CheckResult("moved", EN + "Firewall_(computing)", "article renamed")),
        ("Q5", EN + "Firewall_(computing)", CheckResult("ok", reason="Q5 merged into Q80998")),
        ("Q6", EN + "Gone", CheckResult("dead", reason="Q6 deleted")),
        ("Q1", EN + "Firewall", CheckResult("dead", reason="Q1 has no EN or BG article")),
        ("Q4", EN + "Packet_filter", CheckResult("moved", BG + "Филтър", "no enwiki article")),
        ("Q80998", "https://www.wikidata.org/wiki/Q80998", CheckResult("ok")),
    ],
)
def test_wikidata_check(qid, url, expected) -> None:
    assert live(Wikidata, wikidata_api).check(LinkRecord("wikidata", qid, url)) == expected


# --- wiktionary -------------------------------------------------------------


@pytest.fixture
def wiktionary_index(tmp_path: Path) -> Path:
    source = load_source("wiktionary")
    from conftest import fixture_snapshot

    shard = tmp_path / "shard-wiktionary.sqlite"
    build_shard(source, fixture_snapshot(get_adapter(source)), shard)
    combine([shard], tmp_path / "index.sqlite", "index-w")
    return tmp_path / "index.sqlite"


def toc(title, *sections, pageid=1):
    return {
        "parse": {
            "title": title,
            "pageid": pageid,
            "tocdata": {"sections": [{"tocLevel": 1, "line": s} for s in sections]},
        }
    }


WIKT = "https://en.wiktionary.org/wiki/"


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        (toc("hash table", "English", "Translingual"), CheckResult("ok")),
        (toc("hash-table", "English"), CheckResult("moved", WIKT + "hash-table#English", "page moved")),
        (toc("hash table", "German"), CheckResult("dead", reason="'hash table' has no English section")),
        ({"error": {"code": "nosuchpageid"}}, CheckResult("dead", reason="page 3207720 does not exist")),
        ({"error": {"code": "ratelimited", "info": "slow down"}}, CheckResult("unknown", reason="slow down")),
        (http_error(503), CheckResult("unknown", reason="HTTP 503")),
    ],
)
def test_wiktionary_check(wiktionary_index: Path, answer, expected) -> None:
    with load_providers(wiktionary_index, env={}) as registry:
        provider = registry.providers["wiktionary"]
        assert isinstance(provider, WiktionaryProvider)
        provider.http = FakeHttp(lambda url, params: answer)
        hit = provider.search("hash table")[0]  # search stays in the index
        assert provider.check(LinkRecord(hit.source, hit.external_id, hit.url)) == expected
        url, params = provider.http.calls[0]
        assert url == "https://en.wiktionary.org/w/api.php" and params["pageid"] == "3207720"


def test_wiktionary_check_by_title_and_bg(wiktionary_index: Path) -> None:
    with load_providers(wiktionary_index, env={}) as registry:
        provider = registry.providers["wiktionary"]
        provider.http = FakeHttp(lambda url, params: toc("компютър", "Български"))
        bg = provider.search("компютър")[0]
        assert provider.check(LinkRecord(bg.source, bg.external_id, bg.url)) == CheckResult("ok")
        provider.http = FakeHttp(lambda url, params: toc("colour", "English"))
        link = LinkRecord("wiktionary", "en:colour", WIKT + "colour#English")  # not in the index
        assert provider.check(link) == CheckResult("ok")
        assert provider.http.calls[0][1]["page"] == "colour"
    with load_providers(wiktionary_index, env={}, live=False) as registry:
        assert not isinstance(registry.providers["wiktionary"], WiktionaryProvider)


# --- w3c --------------------------------------------------------------------

TR = "https://www.w3.org/TR/"
CATALOG = [
    ("css-grid-1", "CSS Grid Layout Module Level 1"),
    ("css-grid-2", "CSS Grid Layout Module Level 2"),
    ("css3-grid-align", "Grid Layout"),
    ("WCAG22", "Web Content Accessibility Guidelines (WCAG) 2.2"),
    ("xhtml2", "XHTML™ 2.0"),
    ("webrtc", "WebRTC: Real-Time Communication in Browsers"),
    ("webrtc-stats", "Identifiers for WebRTC's Statistics API"),
]
SPECS = {
    "css-grid-1": {"shortname": "css-grid-1", "shortlink": TR + "css-grid-1/", "description": "<p>Grid <b>1</b></p>"},
    "css-grid-2": {"shortname": "css-grid-2", "shortlink": TR + "css-grid-2/"},
    "css3-grid-align": {"shortname": "css3-grid-align", "_links": {"latest-version": {"title": "Retired"}}},
    "WCAG22": {"shortname": "WCAG22", "shortlink": TR + "WCAG22/"},
    "xhtml2": {"shortname": "xhtml2", "shortlink": TR + "xhtml2/", "_links": {"latest-version": {"title": "Retired"}}},
    "webrtc": {"shortname": "webrtc", "shortlink": TR + "webrtc/"},
    "webrtc-stats": {"shortname": "webrtc-stats", "shortlink": TR + "webrtc-stats/"},
    "css3-grid-layout": {"shortname": "css-grid-1", "shortlink": TR + "css-grid-1/"},  # after the redirect
}


def w3c_api(url, params):
    if url.endswith("/specifications"):
        page = int(params["page"])
        items = [{"href": f"https://api.w3.org/specifications/{s}", "title": t} for s, t in CATALOG]
        return {"pages": 2, "_links": {"specifications": items[:4] if page == 1 else items[4:]}}
    shortname = url.rsplit("/", 1)[1]
    if shortname not in SPECS:
        return http_error(404)
    return SPECS[shortname]


def test_w3c_search() -> None:
    provider = live(W3c, w3c_api)
    hits = provider.search("CSS Grid Layout")
    assert [(h.external_id, h.match) for h in hits] == [("css-grid-2", "alias"), ("css-grid-1", "alias")]
    assert hits[1].snippet == "Grid 1" and hits[1].kind == "document"
    assert [h.external_id for h in provider.search("grid layout")] == ["css-grid-2", "css-grid-1"]  # retired skipped
    assert [(h.external_id, h.match) for h in provider.search("WCAG")] == [("WCAG22", "alias")]
    assert [(h.external_id, h.match) for h in provider.search("webrtc")] == [
        ("webrtc", "exact"),
        ("webrtc-stats", "fts"),
    ]
    assert provider.search("webrtc", lang="bg") == []
    catalog_calls = [c for c in provider.http.calls if c[0].endswith("/specifications")]
    assert len(catalog_calls) == 2  # read once, both pages


@pytest.mark.parametrize(
    ("shortname", "url", "expected"),
    [
        ("css-grid-1", TR + "css-grid-1/", CheckResult("ok")),
        ("xhtml2", TR + "xhtml2/", CheckResult("ok", reason="retired")),
        (
            "css3-grid-layout",
            TR + "css3-grid-layout/",
            CheckResult("moved", TR + "css-grid-1/", "css3-grid-layout is now css-grid-1"),
        ),
        ("nope", TR + "nope/", CheckResult("dead", reason="HTTP 404")),
    ],
)
def test_w3c_check(shortname, url, expected) -> None:
    assert live(W3c, w3c_api).check(LinkRecord("w3c", shortname, url)) == expected


# --- eur-lex ----------------------------------------------------------------


def binding(celex, title, force="1", date="2020-01-01"):
    row = {"celex": {"value": celex}, "title": {"value": title}, "date": {"value": date}}
    return row | ({"force": {"value": force}} if force is not None else {})


GDPR = (
    "Regulation (EU) 2016/679 of the European Parliament and of the Council of 27 April 2016 on the protection "
    "of natural persons (General Data Protection Regulation) (Text with EEA relevance)"
)
ROWS = [
    binding("32026D0001", "Commission Implementing Decision (EU) 2026/1 on personal data", date="2026-01-01"),
    binding("31995L0046", "Directive 95/46/EC of the European Parliament and of the Council on personal data", "0"),
    binding("32016R0679", GDPR),
    binding("32018R1725", "Regulation (EU) 2018/1725 of the European Parliament and of the Council on personal data"),
    binding("32016R0679", GDPR),  # one row per expression
]


def test_eurlex_search() -> None:
    provider = live(Eurlex, lambda url, params: {"results": {"bindings": ROWS}})
    hits = provider.search("general data protection regulation")
    assert [(h.external_id, h.match) for h in hits] == [
        ("32016R0679", "exact"),
        ("32018R1725", "fts"),  # in force, of the Parliament and Council
        ("32026D0001", "fts"),  # in force
        ("31995L0046", "fts"),
    ]
    assert hits[0].matched_label == "General Data Protection Regulation"
    assert hits[0].url == "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32016R0679"
    sparql = provider.http.calls[0][1]["query"]
    assert "'\"general data protection regulation\"'" in sparql and "language/ENG" in sparql
    provider.search("защита на данните", lang="bg")
    assert "language/BUL" in provider.http.calls[1][1]["query"]
    provider.search("C++ ' OR 1=1")
    assert "'\"C OR 1 1\"'" in provider.http.calls[2][1]["query"]  # no quote gets into the query


def test_eurlex_phrase() -> None:
    assert phrase("""it's "data" & AND x""") == '"it s data AND x"'
    assert phrase("--") is None


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        (303, CheckResult("ok")),
        (404, CheckResult("dead", reason="HTTP 404")),
        (500, CheckResult("unknown", reason="HTTP 500")),
    ],
)
def test_eurlex_check(code, expected) -> None:
    provider = live(Eurlex, statuses={"https://publications.europa.eu/resource/celex/32016R0679": (code, None)})
    link = LinkRecord("eurlex", "32016R0679", "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32016R0679")
    assert provider.check(link) == expected


# --- lexit ------------------------------------------------------------------

# The portal's markup with invented text: its dictionaries are all rights reserved.
LEXIT_HIT = """<div class="col-md-7"><form><input name="word" value="думата"/></form>
<h3>Основна форма: ду̀ма<small class="tolowercase"> - Съществително нарицателно</small></h3>
<h4>Форми:</h4><blockquote>ду̀ми - множествено число</blockquote>
<h4>Резултати от: <a href="//ibl.bas.bg/rbe/lang/bg/дума/">Речник на българския език</a></h4>
<blockquote>измислен текст</blockquote>
<h4>Резултати от: неологизми в Инфолекс:</h4><blockquote>измислен текст</blockquote></div>"""
LEXIT_EMPTY = """<div class="col-md-7"><form><input name="word" value="ъъъ"/></form></div>"""
PORTAL = "https://ibl.bas.bg/dictionary_portal/lang/bg/"


def test_lexit_results() -> None:
    assert results(LEXIT_HIT) == ("дума", ["Речник на българския език", "неологизми в Инфолекс"])
    assert results(LEXIT_EMPTY) == (None, [])


def test_lexit_search() -> None:
    provider = live(Lexit, lambda url, params: LEXIT_HIT)
    [hit] = provider.search("думата")
    assert (hit.external_id, hit.match, hit.url) == ("дума", "alias", PORTAL + "%D0%B4%D1%83%D0%BC%D0%B0")
    assert hit.title == "дума (Речник на българския език, неологизми в Инфолекс)" and hit.snippet is None
    assert provider.search("дума")[0].match == "exact"
    assert provider.search("word") == [] and provider.search("дума", lang="en") == []
    assert len(provider.http.calls) == 2  # no request for Latin script or another language
    assert live(Lexit, lambda url, params: LEXIT_EMPTY).search("ъъъ") == []


def test_lexit_check() -> None:
    url = PORTAL + "%D0%B4%D1%83%D0%BC%D0%B0"
    assert live(Lexit, lambda u, p: LEXIT_HIT).check(LinkRecord("lexit", "дума", url)) == CheckResult("ok")
    assert live(Lexit, lambda u, p: LEXIT_EMPTY).check(LinkRecord("lexit", "дума", url)) == CheckResult(
        "dead", reason="no result on the portal"
    )
    assert Lexit.daily == 500 and Lexit({}).http.daily == 500


# --- etymonline -------------------------------------------------------------


def test_etymonline() -> None:
    entries = parse_fixture("etymonline")
    assert sorted(entries) == ["*kwo-", "Patriot Act", "e-mail", "firewall", "will-o'-the-wisp"]
    assert entries["Patriot Act"].url == "https://www.etymonline.com/word/Patriot%20Act"
    assert entries["firewall"].snippet is None and entries["firewall"].kind == "term"


def test_etymonline_snapshot_ignores_lastmod(tmp_path: Path) -> None:
    adapter = get_adapter(load_source("etymonline"))
    copy = tmp_path / "words.xml"
    shutil.copy(ETYMONLINE, copy)
    before = adapter.snapshot(copy).sha256
    copy.write_text(copy.read_text().replace("2019-02-03", "2026-10-23"))
    assert adapter.snapshot(copy).sha256 == before
    copy.write_text(copy.read_text().replace("firewall", "firewalls"))
    assert adapter.snapshot(copy).sha256 != before


def test_candidates_are_json_serializable() -> None:
    hit = live(Wikidata, wikidata_api).search("firewall")[0]
    assert json.loads(json.dumps(hit.__dict__))["source"] == "wikidata"

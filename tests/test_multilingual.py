from pathlib import Path

from conftest import IATE_ZIP, fixture_snapshot, load_source, parse_fixture

from terminology_indexes.build import build_shard, combine
from terminology_indexes.ingest import get_adapter
from terminology_indexes.ingest.iate import export_date
from terminology_indexes.ingest.mediawiki import page_url
from terminology_indexes.model import Label
from terminology_indexes.providers import load_providers


def test_iate() -> None:
    snapshot = get_adapter(load_source("iate")).snapshot(IATE_ZIP)
    assert snapshot.snapshot_version == f"2019-02-26+{snapshot.sha256[:12]}"
    entries = parse_fixture("iate")
    # 14: Romanian only; 1000: only an unverified term; 1002: only a superseded name
    assert sorted(entries, key=int) == ["84", "7128", "60331", "176235", "794344"]
    assert (entries["84"].lang, entries["84"].url) == ("mul", "https://iate.europa.eu/entry/result/84")
    assert entries["7128"].lang == "en"
    lan = entries["794344"]
    assert (lan.title, lan.kind, lan.snippet, lan.extra) == (
        "local area network",
        "concept",
        None,
        {"domain": ["3226", "3236"]},
    )
    # preferred term first; deprecated -> redirect; phrases are not labels
    assert lan.labels == [
        Label("local area network", "en", "pref"),
        Label("LAN", "en", "alt"),
        Label("local network", "en", "redirect"),
        Label("компютърна мрежа", "bg", "pref"),
        Label("мрежа", "bg", "alt"),
    ]


def test_export_date() -> None:
    assert export_date("IATE_export_26022019.tbx") == "2019-02-26"
    assert export_date("export.tbx") == "undated"


def test_eurovoc() -> None:
    entries = parse_fixture("eurovoc")
    # the domain "12 LAW" is another scheme; 9999 has neither EN nor BG
    assert sorted(entries) == [f"http://eurovoc.europa.eu/{n}" for n in ("4038", "56", "7869")]
    ec = entries["http://eurovoc.europa.eu/4038"]
    assert ec.url == "https://op.europa.eu/en/web/eu-vocabularies/concept/-/resource?uri=http://eurovoc.europa.eu/4038"
    assert (ec.title, ec.lang, ec.kind, ec.extra) == ("European Commission", "mul", "concept", {"notation": "4038"})
    assert ec.labels == [
        Label("European Commission", "en", "pref"),
        Label("EC Commission", "en", "alt"),
        Label("CEC", "en", "alt"),
        Label("Европейска комисия", "bg", "pref"),
    ]
    esa = entries["http://eurovoc.europa.eu/56"]
    assert esa.snippet == "System of accounting used to compile national accounts."
    assert Label("ЕСС", "bg", "alt") in esa.labels
    assert entries["http://eurovoc.europa.eu/7869"].lang == "en"
    snapshot = get_adapter(load_source("eurovoc")).snapshot(Path(__file__).parent / "fixtures" / "eurovoc")
    assert snapshot.snapshot_version.startswith("4.24+")


def test_wiktionary() -> None:
    entries = parse_fixture("wiktionary")
    assert sorted(entries) == ["bg:карта", "bg:компютър", "en:e-mail", "en:hash table", "en:map"]
    ht = entries["en:hash table"]
    assert (ht.url, ht.lang, ht.extra) == (
        "https://en.wiktionary.org/wiki/hash_table#English",
        "en",
        {"pageid": 3207720},
    )
    assert ht.labels == [Label("hash table", "en", "pref")]
    pc = entries["bg:компютър"]
    assert pc.url == "https://bg.wiktionary.org/wiki/%D0%BA%D0%BE%D0%BC%D0%BF%D1%8E%D1%82%D1%8A%D1%80"
    assert pc.labels == [Label("компютър", "bg", "pref")]


def test_eom() -> None:
    entries = parse_fixture("eom")
    assert entries["9077"].url == "https://encyclopediaofmath.org/wiki/Turing_machine"
    assert entries["9077"].labels == [Label("Turing machine", "en", "pref")]


def test_page_url() -> None:
    assert page_url("https://w/wiki/", "C++") == "https://w/wiki/C%2B%2B"
    assert page_url("https://w/wiki/", "a/b (c)") == "https://w/wiki/a/b_(c)"


def test_bilingual_bonus(tmp_path: Path) -> None:
    """IATE has "firewall" alone, and "Internet firewall" (alias "firewall") with the BG "защитна стена"."""
    shards = []
    for sid in ("iate", "eurovoc"):
        source = load_source(sid)
        adapter = get_adapter(source)
        shard = tmp_path / f"shard-{sid}.sqlite"
        build_shard(source, fixture_snapshot(adapter), shard)
        shards.append(shard)
    index = tmp_path / "index.sqlite"
    combine(shards, index, "index-test")
    with load_providers(index, env={}, live=False) as registry:
        plain = registry.search_all("firewall", lang="en")
        assert [(h.external_id, h.match, h.also_matched) for h in plain] == [
            ("60331", "exact", None),
            ("176235", "alias", None),
        ]
        both = registry.search_all("firewall", translation="защитна стена", lang="en")
        assert [(h.external_id, h.match, h.also_matched) for h in both] == [
            ("176235", "alias", "защитна стена"),
            ("60331", "exact", None),
        ]
        fts = registry.search_all("network", translation="компютърна мрежа", lang="en")
        assert [(h.external_id, h.match, h.also_matched) for h in fts] == [("794344", "fts", "компютърна мрежа")]
        # the bonus lifts an alias to the level of an exact match
        ec = registry.search_all("CEC", translation="Европейска комисия", lang="en")
        assert [(h.external_id, h.also_matched) for h in ec] == [
            ("http://eurovoc.europa.eu/4038", "Европейска комисия")
        ]

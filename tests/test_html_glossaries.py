import io
import urllib.error
from pathlib import Path

import pytest
from conftest import HTML_PAGES, load_source, parse_fixture

from terminology_indexes.ingest import get_adapter, html_page
from terminology_indexes.ingest.html_page import RobotsDenied, robots_allowed


def labels(entry) -> list[tuple[str, str]]:
    return [(l.label, l.label_type) for l in entry.labels]


def test_postgresql() -> None:
    entries = parse_fixture("postgresql_glossary")
    # only <dt id> inside the glosslist
    assert sorted(entries) == [
        "GLOSSARY-ACID",
        "GLOSSARY-ANALYZE",
        "GLOSSARY-INSTANCE",
        "GLOSSARY-IO",
        "GLOSSARY-REPLICA",
    ]
    acid = entries["GLOSSARY-ACID"]
    assert acid.url == "https://www.postgresql.org/docs/current/glossary.html#GLOSSARY-ACID"
    assert acid.snippet == "Atomicity, Consistency, Isolation, and Durability."
    assert labels(entries["GLOSSARY-IO"]) == [("Input/Output (I/O)", "pref"), ("Input/Output", "alt"), ("I/O", "alt")]
    assert labels(entries["GLOSSARY-ANALYZE"]) == [("Analyze (operation)", "pref"), ("Analyze", "alt")]
    # "Database server — See Instance" has no anchor: a redirect label of the target
    assert ("Database server", "redirect") in labels(entries["GLOSSARY-INSTANCE"])
    assert {("Standby (server)", "redirect"), ("Standby", "redirect")} <= set(labels(entries["GLOSSARY-REPLICA"]))


def test_unicode() -> None:
    entries = parse_fixture("unicode_glossary")
    # letter headings and paragraphs without a self-link are not terms
    assert sorted(entries) == ["BNF", "BOM", "abjad", "abstract_character", "byte_order_mark", "code_point"]
    assert entries["abjad"].url == "https://www.unicode.org/glossary/#abjad"
    assert entries["abstract_character"].title == "Abstract Character"
    assert all(e.snippet is None for e in entries.values())  # snippet_policy: none, and none parsed
    assert labels(entries["BOM"]) == [("BOM", "pref"), ("byte order mark", "alt")]
    assert labels(entries["BNF"])[1] == ("Backus-Naur Form", "alt")  # without the lowercase aside


def test_google_ml() -> None:
    entries = parse_fixture("google_ml")
    # h2.hide-from-toc only: not the letters, not "Page Summary"
    assert list(entries) == [
        "accuracy",
        "auc-area-under-the-roc-curve",
        "node-decision-tree",
        "vertex",
        "empty",
        "last",
    ]
    accuracy = entries["accuracy"]
    assert accuracy.url == "https://developers.google.com/machine-learning/glossary#accuracy"
    assert accuracy.snippet == "Fixture: the number of correct predictions divided by the total number of predictions."
    assert accuracy.extra == {"tags": ["ML Fundamentals", "Metric"]}
    auc = entries["auc-area-under-the-roc-curve"]
    assert labels(auc) == [
        ("AUC (Area under the ROC curve)", "pref"),
        ("AUC", "alt"),
        ("Area under the ROC curve", "alt"),
    ]
    assert entries["node-decision-tree"].extra is None
    assert entries["vertex"].snippet == "Fixture: the definition in the same paragraph as the heading."
    assert entries["empty"].snippet is None and entries["last"].snippet is None


def test_snapshot_hashes_entries_not_bytes(tmp_path: Path) -> None:
    adapter = get_adapter(load_source("google_ml"))
    page = tmp_path / "page.html"
    page.write_text(HTML_PAGES["google_ml"].read_text().replace('nonce="fixture"', 'nonce="other"'))
    before = adapter.snapshot(HTML_PAGES["google_ml"])
    assert adapter.snapshot(page).sha256 == before.sha256
    assert before.snapshot_version == before.sha256[:12]
    page.write_text(HTML_PAGES["google_ml"].read_text().replace(" accuracy</h2>", " precision</h2>"))
    assert adapter.snapshot(page).sha256 != before.sha256


@pytest.fixture
def robots(monkeypatch):
    def serve(text: str | None = None, code: int = 200):
        def urlopen(request, timeout):
            if text is None:
                raise urllib.error.HTTPError(request.full_url, code, "x", {}, None)
            return io.BytesIO(text.encode())

        monkeypatch.setattr(html_page.urllib.request, "urlopen", urlopen)

    return serve


def test_robots(robots) -> None:
    robots("User-agent: *\nDisallow: /docs/devel/\n")
    assert robots_allowed("https://www.postgresql.org/docs/18/glossary.html")
    assert not robots_allowed("https://www.postgresql.org/docs/devel/glossary.html")
    robots("User-agent: terminology-indexes\nDisallow: /\n")
    assert not robots_allowed("https://example.org/page.html")
    robots(None, 404)
    assert robots_allowed("https://example.org/page.html")
    robots(None, 403)
    assert not robots_allowed("https://example.org/page.html")


def test_fetch_respects_robots(robots, tmp_path: Path) -> None:
    robots("User-agent: *\nDisallow: /\n")
    with pytest.raises(RobotsDenied):
        get_adapter(load_source("unicode_glossary")).fetch(tmp_path)

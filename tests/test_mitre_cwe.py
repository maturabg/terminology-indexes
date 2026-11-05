import zipfile
from pathlib import Path

import pytest
from conftest import CWE_ZIP, load_source, parse_fixture

from terminology_indexes.ingest import get_adapter
from terminology_indexes.ingest.mitre_cwe import replacement
from terminology_indexes.model import Label


def test_snapshot() -> None:
    snapshot = get_adapter(load_source("mitre_cwe")).snapshot(CWE_ZIP)
    assert snapshot.snapshot_version == f"5.0+{snapshot.sha256[:12]}"


def test_parse() -> None:
    entries = parse_fixture("mitre_cwe")
    assert sorted(entries) == ["CWE-1", "CWE-1187", "CWE-16", "CWE-217", "CWE-699", "CWE-79", "CWE-89", "CWE-908"]
    xss = entries["CWE-79"]
    assert xss.url == "https://cwe.mitre.org/data/definitions/79.html"
    assert (xss.kind, xss.status, xss.extra["type"], xss.extra["abstraction"]) == (
        "concept",
        "active",
        "weakness",
        "Base",
    )
    assert xss.snippet.startswith("The product does not neutralize")
    # the id and every Alternate_Term is a label; "a / b / c" is three
    assert xss.labels[:3] == [
        Label("Improper Neutralization of Input During Web Page Generation", "en", "pref"),
        Label("CWE-79", "en", "alt"),
        Label("Cross-site Scripting", "en", "alt"),
    ]
    assert {"Reflected XSS", "Non-Persistent XSS", "Type 1 XSS"} <= {l.label for l in xss.labels}
    assert entries["CWE-699"].kind == "document"
    assert (entries["CWE-16"].kind, entries["CWE-16"].extra["type"]) == ("concept", "grouping")
    # Obsolete is still a page: active, with the CWE status in extra
    assert (entries["CWE-16"].status, entries["CWE-16"].extra["cwe_status"]) == ("active", "Obsolete")


def test_deprecated() -> None:
    entries = parse_fixture("mitre_cwe")
    dup = entries["CWE-1187"]
    assert (dup.status, dup.replaced_by) == ("deprecated", "CWE-908")
    assert (
        dup.title == "DEPRECATED: Use of Uninitialized Resource"
        and dup.labels[0].label == "Use of Uninitialized Resource"
    )
    assert entries["CWE-217"].replaced_by is None  # CWE-766 and CWE-767: split, no single replacement
    assert entries["CWE-1"].replaced_by is None  # mentions only the Development View (CWE-699)


@pytest.mark.parametrize(
    ("before", "after", "missing"),
    [
        (b"http://cwe.mitre.org/cwe-8", b"http://cwe.mitre.org/cwe-9", "'Grouping', 'View', 'Weakness'"),
        (b"Grouping", b"Cluster", "'Grouping'"),
    ],
)
def test_unknown_schema_fails_by_name(tmp_path: Path, before: bytes, after: bytes, missing: str) -> None:
    with zipfile.ZipFile(CWE_ZIP) as z:
        name = z.namelist()[0]
        xml = z.read(name)
    path = tmp_path / "cwec.xml.zip"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(name, xml.replace(before, after))
    adapter = get_adapter(load_source("mitre_cwe"))
    with pytest.raises(ValueError, match=missing):
        list(adapter.parse(adapter.snapshot(path)))


def test_replacement() -> None:
    ids = {"1": "active", "2": "active", "3": "deprecated", "699": "active"}
    assert replacement("duplicate of CWE-1. All content has been transferred to CWE-1.", ids, {"699"}) == "CWE-1"
    assert replacement("can be found at CWE-1 and CWE-2.", ids, {"699"}) is None
    assert replacement("See CWE-3.", ids, {"699"}) is None  # not active
    assert replacement("the Development View (CWE-699) and CWE-2", ids, {"699"}) == "CWE-2"
    assert replacement("See CWE-404.", ids, {"699"}) is None  # unknown

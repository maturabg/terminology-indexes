import base64
import hashlib

import pytest
from conftest import BIBLIO, load_source, parse_fixture

from terminology_indexes.ingest import get_adapter
from terminology_indexes.ingest.ecma262 import check_integrity


def test_snapshot() -> None:
    snapshot = get_adapter(load_source("ecma262")).snapshot(BIBLIO)
    assert snapshot.snapshot_version.startswith("2.2.3203+")


def test_parse() -> None:
    entries = parse_fixture("ecma262")
    # terms and titled clauses; ops, productions and untitled clauses stay out
    assert sorted(entries) == [
        "sec-intro",
        "sec-map.prototype.clear",
        "sec-math.pow",
        "term:Agent Record",
        "term:Legacy",
        "term:thenable",
    ]
    pow_ = entries["sec-math.pow"]
    assert (pow_.url, pow_.title, pow_.kind) == (
        "https://tc39.es/ecma262/#sec-math.pow",
        "Math.pow ( base, exponent )",
        "spec_section",
    )
    assert [l.label for l in pow_.labels] == ["Math.pow"]  # without the signature
    assert [l.label for l in entries["sec-map.prototype.clear"].labels] == ["Map.prototype.clear"]
    assert pow_.extra == {"type": "clause", "number": "21.3.2.26"}
    assert entries["sec-intro"].extra["number"] is None
    thenable = entries["term:thenable"]
    assert (thenable.url, thenable.kind) == ("https://tc39.es/ecma262/#sec-promise-objects", "term")
    assert [(l.label, l.label_type) for l in thenable.labels] == [("thenable", "pref"), ("thenables", "alt")]
    assert entries["term:Agent Record"].url.endswith("#agent-record")  # a term with its own id


def test_check_integrity() -> None:
    digest = base64.b64encode(hashlib.sha512(BIBLIO.read_bytes()).digest()).decode()
    check_integrity(BIBLIO, f"sha512-{digest}")
    with pytest.raises(ValueError, match="does not match"):
        check_integrity(BIBLIO, "sha512-AAAA")

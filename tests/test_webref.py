import json
import shutil
from pathlib import Path

from conftest import WEBREF, load_source, parse_fixture

from terminology_indexes.ingest import get_adapter


def test_parse() -> None:
    entries = parse_fixture("webref")
    # public, normative, top-level, term-like, WHATWG/W3C, not discontinued; first of a duplicate
    assert sorted(entries) == [
        "css-color-4#propdef-color",
        "css-color-4#typedef-color",
        "dom#concept-node-tree",
        "dom#concept-shadow-root",
        "dom#interface-node",
        "fetch#concept-request",
        "fetch#http-access-control-allow-origin",
    ]
    root = entries["dom#concept-shadow-root"]
    assert (root.url, root.title, root.kind) == (
        "https://dom.spec.whatwg.org/#concept-shadow-root",
        "shadow root",
        "spec_section",
    )
    assert [(l.label, l.label_type) for l in root.labels] == [("shadow root", "pref"), ("shadow roots", "alt")]
    assert root.extra == {"spec": "dom", "spec_title": "DOM Standard", "type": "dfn", "license": "CC BY 4.0"}
    color = entries["css-color-4#typedef-color"]
    assert [l.label for l in color.labels] == ["<color>", "color"]
    assert color.extra["license"] == "W3C Document License"


def test_snapshot_ignores_crawl_dates(tmp_path: Path) -> None:
    adapter = get_adapter(load_source("webref"))
    before = adapter.snapshot(WEBREF)
    assert before.snapshot_version == "2026-10-22+07371cb9f34e"
    copy = tmp_path / "webref"
    shutil.copytree(WEBREF, copy)
    index = json.loads((copy / "ed" / "index.json").read_text())
    index["date"] = "2026-10-23"
    (copy / "ed" / "index.json").write_text(json.dumps(index))
    assert adapter.snapshot(copy).sha256 == before.sha256
    index["results"][0]["title"] = "DOM"
    (copy / "ed" / "index.json").write_text(json.dumps(index))
    assert adapter.snapshot(copy).sha256 != before.sha256

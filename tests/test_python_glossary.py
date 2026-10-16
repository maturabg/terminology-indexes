import sqlite3
from pathlib import Path

import pytest
from conftest import FIXTURES

from terminology_indexes.build import BuildError, build_shard, combine, manifest
from terminology_indexes.ingest import get_adapter
from terminology_indexes.ingest.base import sha256_file
from terminology_indexes.search import search

INV = FIXTURES / "python_glossary.objects.inv"


@pytest.fixture
def snapshot(python_glossary):
    return get_adapter(python_glossary).snapshot(INV, sha256_file(INV))


def test_parse_only_terms(python_glossary, snapshot) -> None:
    entries = {e.external_id: e for e in get_adapter(python_glossary).parse(snapshot)}
    assert len(entries) == 9
    assert "os.path.join" not in entries and "glossary" not in entries
    assert entries["decorator"].url == "https://docs.python.org/3/glossary.html#term-decorator"
    assert entries[">>>"].url == "https://docs.python.org/3/glossary.html#term-0"
    assert entries["Python 3000"].url.endswith("#term-Python-3000")
    assert entries["decorator"].kind == "term" and entries["decorator"].lang == "en"
    assert snapshot.snapshot_version.startswith("3.14+")


@pytest.fixture
def index(tmp_path: Path, python_glossary, snapshot) -> Path:
    shard = tmp_path / "shards" / "shard-python_glossary.sqlite"
    assert build_shard(python_glossary, snapshot, shard) == 9
    out = tmp_path / "index.sqlite"
    assert combine([shard], out, "index-test") == {"python_glossary": 9}
    return out


def test_search(index: Path) -> None:
    conn = sqlite3.connect(index)
    hit = search(conn, "Decorator")[0]
    assert (hit.external_id, hit.match) == ("decorator", "exact")
    assert search(conn, "F string")[0].external_id == "f-string"
    assert search(conn, "interpreter lock")[0].match == "fts"
    assert search(conn, "abstract bas")[0].external_id == "abstract base class"  # prefix
    assert search(conn, 'lock" OR "x') == []  # user input is not FTS syntax
    assert search(conn, "decorator", lang="bg") == []


def test_manifest(index: Path) -> None:
    m = manifest(index)
    assert m["schema_version"] == "1" and m["release_tag"] == "index-test"
    assert m["sources"]["python_glossary"]["row_count"] == 9


def test_combine_rejects_other_norm_version(tmp_path: Path, index: Path) -> None:
    shard = next((index.parent / "shards").glob("*.sqlite"))
    with sqlite3.connect(shard) as conn:
        conn.execute("UPDATE meta SET value = '0' WHERE key = 'norm_version'")
    with pytest.raises(BuildError, match="full rebuild"):
        combine([shard], tmp_path / "other.sqlite")

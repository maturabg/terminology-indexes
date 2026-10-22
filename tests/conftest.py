from pathlib import Path

import pytest

from terminology_indexes.build import build_shard, combine
from terminology_indexes.ingest import get_adapter
from terminology_indexes.ingest.base import sha256_file
from terminology_indexes.model import Source

ROOT = Path(__file__).parent.parent
FIXTURES = Path(__file__).parent / "fixtures"
INV = FIXTURES / "python_glossary.objects.inv"


@pytest.fixture
def python_glossary() -> Source:
    return Source.load(ROOT / "sources" / "python_glossary.yaml")


@pytest.fixture
def snapshot(python_glossary):
    return get_adapter(python_glossary).snapshot(INV, sha256_file(INV))


@pytest.fixture
def index(tmp_path: Path, python_glossary, snapshot) -> Path:
    shard = tmp_path / "shards" / "shard-python_glossary.sqlite"
    assert build_shard(python_glossary, snapshot, shard) == 9
    out = tmp_path / "index.sqlite"
    assert combine([shard], out, "index-test") == {"python_glossary": 9}
    return out


NIST_ZIP = FIXTURES / "nist_csrc.glossary-export.zip"


@pytest.fixture
def nist_csrc() -> Source:
    return Source.load(ROOT / "sources" / "nist_csrc.yaml")


@pytest.fixture
def nist_snapshot(nist_csrc):
    return get_adapter(nist_csrc).snapshot(NIST_ZIP)

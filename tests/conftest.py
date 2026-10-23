from importlib import import_module
from pathlib import Path

import pytest

from terminology_indexes.build import build_shard, combine
from terminology_indexes.ingest import ADAPTERS, get_adapter
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


CWE_ZIP = FIXTURES / "mitre_cwe.cwec.xml.zip"
BIBLIO = FIXTURES / "ecma262.biblio.tgz"
WEBREF = FIXTURES / "webref"
GIT_ADOC = FIXTURES / "git_glossary.adoc"
HTML_PAGES = {
    sid: FIXTURES / f"{sid}.html" for sid in ("postgresql_glossary", "unicode_glossary", "google_ml", "nist_dads")
}
# Git sources and OWASP GenAI: a directory laid out like the fetched one
DIRECTORIES = {sid: FIXTURES / sid for sid in ("mdn", "cncf_glossary", "owasp_cheatsheets", "owasp_genai")}
RFC_INDEX = FIXTURES / "rfc_editor.rfc-index.xml"


def load_source(source_id: str) -> Source:
    return Source.load(ROOT / "sources" / f"{source_id}.yaml")


def fixture_snapshot(adapter):
    """The snapshot ``adapter.fetch`` would return, from the committed fixture."""
    match adapter.source.id:
        case "python_glossary":
            return adapter.snapshot(INV, sha256_file(INV))
        case "nist_csrc":
            return adapter.snapshot(NIST_ZIP)
        case "mitre_cwe":
            return adapter.snapshot(CWE_ZIP)
        case "ecma262":
            return adapter.snapshot(BIBLIO)
        case "webref":
            return adapter.snapshot(WEBREF)
        case "git_glossary":
            return adapter.snapshot(GIT_ADOC, sha256_file(GIT_ADOC))
        case "rfc_editor":
            return adapter.snapshot(RFC_INDEX, sha256_file(RFC_INDEX))
        case sid if sid in HTML_PAGES:
            return adapter.snapshot(HTML_PAGES[sid])
        case sid if sid in DIRECTORIES:
            return adapter.snapshot(DIRECTORIES[sid])
    raise LookupError(adapter.source.id)


def parse_fixture(source_id: str) -> dict:
    """``{external_id: Entry}`` of a source's fixture."""
    adapter = get_adapter(load_source(source_id))
    return {e.external_id: e for e in adapter.parse(fixture_snapshot(adapter))}


@pytest.fixture
def offline(monkeypatch):
    """Every adapter's ``fetch`` returns its committed fixture instead of downloading."""
    for target in ADAPTERS.values():
        module, _, name = target.partition(":")
        monkeypatch.setattr(getattr(import_module(module), name), "fetch", lambda self, raw_dir: fixture_snapshot(self))

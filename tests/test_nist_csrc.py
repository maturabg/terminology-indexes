import hashlib
import zipfile

from conftest import NIST_ZIP

from terminology_indexes.ingest import get_adapter
from terminology_indexes.ingest.nist_csrc import clean
from terminology_indexes.model import Label


def test_clean() -> None:
    assert clean("<em><strong>len (a)</strong></em>") == "len (a)"
    assert clean("<em>X<< 1</em>") == "X<< 1"
    assert clean("Date&nbsp;of&nbsp;Birth") == "Date of Birth"
    assert clean("C&amp;S") == "C&S"


def test_snapshot_hashes_the_json(nist_snapshot) -> None:
    with zipfile.ZipFile(NIST_ZIP) as z:
        sha = hashlib.sha256(z.read("glossary-export.json")).hexdigest()
    assert nist_snapshot.sha256 == sha
    assert nist_snapshot.snapshot_version == f"2026-10-17+{sha[:12]}"


def test_parse(nist_csrc, nist_snapshot) -> None:
    entries = {e.external_id: e for e in get_adapter(nist_csrc).parse(nist_snapshot)}
    assert len(entries) == 9
    aes = entries["aes"]
    assert aes.url == "https://csrc.nist.gov/glossary/term/aes"
    assert (aes.title, aes.kind, aes.lang) == ("AES", "term", "en")
    # abbrSyn: the expansion is an alias; a duplicate spelling is dropped
    assert aes.labels == [
        Label("AES", "en", "pref"),
        Label("Advanced Encryption Standard", "en", "alt"),
        Label("Advanced Encryption Standard (algorithm)", "en", "alt"),
    ]
    assert entries["dataset"].title == "Dataset"
    assert entries["c_and_s"].title == "C&S"
    assert entries["x_leftbitshift_1"].title == "X<< 1"


def test_snippet_only_from_nist_publications(nist_csrc, nist_snapshot) -> None:
    entries = {e.external_id: e for e in get_adapter(nist_csrc).parse(nist_snapshot)}
    assert entries["encryption"].snippet.startswith("The process of transforming plaintext into ciphertext")
    assert entries["attandck"].snippet is None  # no definitions
    assert entries["access_authority"].snippet is None  # CNSSI only

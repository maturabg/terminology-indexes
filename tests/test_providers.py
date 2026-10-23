import json
import sqlite3
from compression import zstd
from dataclasses import replace
from pathlib import Path

import pytest

from terminology_indexes import providers
from terminology_indexes.build import combine, create_db, manifest, write_entries
from terminology_indexes.contract import Candidate, CheckResult, LinkRecord, Provider
from terminology_indexes.model import Entry, IndexVersionError, Label
from terminology_indexes.providers import load_providers
from terminology_indexes.release import ReleaseError, unpack_index

DOC = "https://example.org/demo/"


def demo_shard(path: Path, source) -> Path:
    """A second source: an alias, a deprecated entry with and without a replacement."""
    demo = replace(source, id="demo", snippet_policy="none")
    entries = [
        Entry("decorator", DOC + "decorator", "Decorator", "concept", "en", labels=[Label("Decorator", "en")]),
        Entry(
            "wrapper",
            DOC + "wrapper",
            "Wrapper function",
            "concept",
            "en",
            labels=[Label("Wrapper function", "en"), Label("decorator", "en", "alt"), Label("обвивка", "bg")],
        ),
        Entry(
            "old", DOC + "old", "Decorator (old)", "concept", "en", "deprecated", "wrapper", labels=[Label("decorator")]
        ),
        Entry("gone", DOC + "gone", "Gone", "concept", "en", "deprecated", labels=[Label("gone")]),
    ]
    conn = create_db(path, {"shard": "demo"})
    with conn:
        rows = write_entries(conn, demo, entries)
        conn.execute("INSERT INTO sources VALUES ('demo', 'v1', '', '', ?, 'open', 'demo')", (rows,))
        conn.execute("INSERT INTO labels_fts(labels_fts) VALUES ('rebuild')")
    conn.close()
    return path


@pytest.fixture
def two_sources(index: Path, python_glossary) -> Path:
    shards = index.parent / "shards"
    demo_shard(shards / "shard-demo.sqlite", python_glossary)
    out = index.parent / "two.sqlite"
    combine(shards.glob("shard-*.sqlite"), out, "index-two")
    return out


def test_registry_has_one_provider_per_indexed_source(two_sources: Path) -> None:
    with load_providers(two_sources, env={}, live=False) as registry:
        assert sorted(registry.providers) == ["demo", "python_glossary"]
        assert all(isinstance(p, Provider) for p in registry.providers.values())
        hit = registry.providers["python_glossary"].search("decorator")[0]
    assert hit == Candidate(
        source="python_glossary",
        external_id="decorator",
        url="https://docs.python.org/3/glossary.html#term-decorator",
        title="decorator",
        kind="term",
        matched_label="decorator",
        match="exact",
        snippet=None,
        snapshot_version="index-two",
    )


def test_search_all_ranks_exact_alias_fts(two_sources: Path) -> None:
    with load_providers(two_sources, env={}, live=False) as registry:
        hits = registry.search_all("decorator", per_source=3)
        assert [(h.source, h.external_id, h.match) for h in hits] == [
            ("demo", "decorator", "exact"),
            ("python_glossary", "decorator", "exact"),
            ("demo", "wrapper", "alias"),
        ]  # "old" is deprecated: never a search result
        assert len(registry.search_all("decorator", per_source=1)) == 2
        assert len(registry.search_all("decorator", limit=1)) == 1
        assert [h.source for h in registry.search_all("decorator", sources=["python_glossary"])] == ["python_glossary"]
        assert [h.external_id for h in registry.search_all("обвивка", lang="bg")] == ["wrapper"]
        with pytest.raises(ValueError, match="unknown source"):
            registry.search_all("decorator", sources=["nope"])


@pytest.mark.parametrize(
    ("link", "expected"),
    [
        (LinkRecord("demo", "decorator", DOC + "decorator"), CheckResult("ok")),
        (LinkRecord("demo", "decorator", "http://old/"), CheckResult("moved", DOC + "decorator", "url changed")),
        (
            LinkRecord("demo", "old", DOC + "old"),
            CheckResult("moved", DOC + "wrapper", "deprecated, replaced by wrapper"),
        ),
        (
            LinkRecord("demo", "gone", DOC + "gone"),
            CheckResult("dead", None, "deprecated without an active replacement"),
        ),
        (LinkRecord("demo", "missing", DOC), CheckResult("dead", None, "not in demo index-two")),
        (LinkRecord("nope", "x", DOC), CheckResult("unknown", None, "no provider for 'nope'")),
    ],
)
def test_check(two_sources: Path, link: LinkRecord, expected: CheckResult) -> None:
    with load_providers(two_sources, env={}, live=False) as registry:
        assert registry.check(link) == expected


def test_refuses_other_schema_version(index: Path) -> None:
    with sqlite3.connect(index) as conn:
        conn.execute("UPDATE meta SET value = '99' WHERE key = 'schema_version'")
    with pytest.raises(IndexVersionError, match="schema_version '99'"):
        load_providers(index, env={}, live=False)


class FakeLive:
    id = "fake_live"
    secret_env = "FAKE_KEY"

    def __init__(self, env) -> None:
        self.key = env["FAKE_KEY"]

    def search(self, query, *, lang=None, limit=5):
        raise TimeoutError("api down")

    def check(self, link):
        return CheckResult("unknown", reason="api down")


def test_live_provider_needs_its_secret(monkeypatch, index: Path) -> None:
    monkeypatch.setattr(providers, "LIVE_PROVIDERS", {"fake_live": f"{__name__}:FakeLive"})
    with load_providers(index, env={}) as registry:
        assert "fake_live" not in registry.providers
    with load_providers(index, env={"FAKE_KEY": "k"}) as registry:
        assert "fake_live" in registry.providers
        # a failing provider does not break the others
        assert [h.source for h in registry.search_all("decorator")] == ["python_glossary"]


def test_unpack_index_verifies_sha(tmp_path: Path, index: Path) -> None:
    archive = tmp_path / "index.sqlite.zst"
    archive.write_bytes(zstd.compress(index.read_bytes()))
    good = tmp_path / "manifest.json"
    good.write_text(json.dumps(manifest(index)))
    out = unpack_index(archive, good, tmp_path / "dl" / "index.sqlite")
    assert out.read_bytes() == index.read_bytes()

    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(manifest(index) | {"index_sha256": "0" * 64}))
    with pytest.raises(ReleaseError, match="does not match"):
        unpack_index(archive, bad, tmp_path / "x.sqlite")
    assert not (tmp_path / "x.sqlite").exists()

    bad.write_text(json.dumps(manifest(index) | {"schema_version": "99"}))
    with pytest.raises(IndexVersionError):
        unpack_index(archive, bad, tmp_path / "x.sqlite")

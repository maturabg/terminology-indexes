from conftest import GIT_ADOC, load_source, parse_fixture

from terminology_indexes.ingest import get_adapter
from terminology_indexes.ingest.base import sha256_file


def labels(entry) -> list[tuple[str, str]]:
    return [(l.label, l.label_type) for l in entry.labels]


def test_parse() -> None:
    entries = parse_fixture("git_glossary")
    assert len(entries) == 8
    commit = entries["def_commit"]
    assert (commit.url, commit.title, commit.kind) == (
        "https://git-scm.com/docs/gitglossary#def_commit",
        "commit",
        "term",
    )
    assert labels(entries["def_commit-ish"]) == [
        ("commit-ish (also committish)", "pref"),
        ("commit-ish", "alt"),
        ("committish", "alt"),
    ]
    assert labels(entries["def_object_identifier"]) == [
        ("object identifier", "pref"),
        ("object ID", "alt"),
        ("oid", "alt"),
    ]
    assert labels(entries["def_commit_graph_general"]) == [("commit graph concept, representations and usage", "pref")]


def test_obsolete_name_redirects() -> None:
    entries = parse_fixture("git_glossary")
    cache = entries["def_cache"]
    assert (cache.status, cache.replaced_by) == ("redirect", "def_index")
    assert labels(entries["def_index"]) == [("index", "pref"), ("cache", "redirect")]


def test_snapshot() -> None:
    snapshot = get_adapter(load_source("git_glossary")).snapshot(GIT_ADOC, sha256_file(GIT_ADOC))
    assert snapshot.snapshot_version == f"master+{snapshot.sha256[:12]}"

import json
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from conftest import ROOT

from terminology_indexes.build import BuildError
from terminology_indexes.cli import main
from terminology_indexes.ingest.nist_csrc import NistCsrc
from terminology_indexes.model import load_registry, parse_period
from terminology_indexes.refresh import assemble, notice, plan, read_json, refresh_source, shard_name

NOW = datetime(2026, 10, 18, 20, 47, tzinfo=UTC)


@pytest.fixture
def registry():
    """Two sources are enough for the refresh logic; ``test_refresh_all_sources`` runs every one."""
    full = load_registry(ROOT / "sources")
    return {sid: full[sid] for sid in ("nist_csrc", "python_glossary")}


@pytest.fixture(autouse=True)
def _offline(offline):
    pass


def seen(**checked: timedelta) -> dict:
    return {"sources": {sid: {"checked_at": (NOW - ago).isoformat()} for sid, ago in checked.items()}}


def run_all(registry, tmp_path: Path, previous: dict, name: str, **kw) -> dict:
    """One whole refresh: plan, a shard job per due source, assemble."""
    due = plan(registry, previous, at=NOW, **kw)
    new = tmp_path / name / "new"
    for sid in due:
        refresh_source(registry[sid], tmp_path / "raw", new, previous, force=kw.get("force", False))
    return assemble(
        registry,
        due=due,
        new_dir=new,
        previous_dir=tmp_path / name / "previous",
        previous=previous,
        out=tmp_path / name / "index.sqlite",
        release_tag=f"index-{name}",
        force=kw.get("force", False),
    )


def test_parse_period() -> None:
    assert parse_period("P1D") == timedelta(days=1)
    assert parse_period("P2W") == timedelta(days=14)
    assert parse_period("P1M") == timedelta(days=30)
    with pytest.raises(ValueError):
        parse_period("PT1H")


def test_plan(registry) -> None:
    assert plan(registry, {}, at=NOW) == ["nist_csrc", "python_glossary"]
    # P1D is due a bit early (cron jitter); P7D is not due after six days
    assert plan(registry, seen(nist_csrc=timedelta(hours=23), python_glossary=timedelta(days=6)), at=NOW) == [
        "nist_csrc"
    ]
    assert plan(registry, seen(nist_csrc=timedelta(hours=11), python_glossary=timedelta(days=7)), at=NOW) == [
        "python_glossary"
    ]
    assert plan(registry, seen(nist_csrc=timedelta(0), python_glossary=timedelta(0)), at=NOW, force=True) == [
        "nist_csrc",
        "python_glossary",
    ]
    assert plan(registry, {}, at=NOW, only=["python_glossary"]) == ["python_glossary"]
    with pytest.raises(BuildError, match="not buildable"):
        plan(registry, {}, at=NOW, only=["wikidata"])


def test_refresh_source(registry, tmp_path: Path) -> None:
    nist = registry["nist_csrc"]
    status = refresh_source(nist, tmp_path / "raw", tmp_path / "a", {})
    assert status["outcome"] == "built" and status["rows"] == 9
    assert (tmp_path / "a" / shard_name("nist_csrc")).exists()
    assert read_json(tmp_path / "a" / "status-nist_csrc.json") == status

    previous = {"sources": {"nist_csrc": {"raw_sha256": status["raw_sha256"]}}}
    assert refresh_source(nist, tmp_path / "raw", tmp_path / "b", previous)["outcome"] == "unchanged"
    assert not (tmp_path / "b" / shard_name("nist_csrc")).exists()
    assert refresh_source(nist, tmp_path / "raw", tmp_path / "c", previous, force=True)["outcome"] == "built"


def test_refresh_source_failure_is_a_status(registry, tmp_path: Path, monkeypatch) -> None:
    def boom(self, raw_dir):
        raise OSError("HTTP Error 403: Forbidden")

    monkeypatch.setattr(NistCsrc, "fetch", boom)
    status = refresh_source(registry["nist_csrc"], tmp_path / "raw", tmp_path / "a", {})
    assert status["outcome"] == "failed" and status["message"] == "OSError: HTTP Error 403: Forbidden"
    assert read_json(tmp_path / "a" / "status-nist_csrc.json")["outcome"] == "failed"


def copy_shards(src: Path, dst: Path) -> None:
    """The previous release: shards of the last index."""
    dst.mkdir(parents=True)
    for shard in src.glob("shard-*.sqlite"):
        (dst / shard.name).write_bytes(shard.read_bytes())


def test_refresh_cycle(registry, tmp_path: Path) -> None:
    first = run_all(registry, tmp_path, {}, "1")
    assert first["changed"]
    m1 = first["manifest"]
    assert m1["release_tag"] == "index-1"
    assert {sid: s["outcome"] for sid, s in m1["sources"].items()} == {
        "nist_csrc": "built",
        "python_glossary": "built",
    }
    assert m1["sources"]["nist_csrc"]["row_count"] == 9 and m1["sources"]["nist_csrc"]["checked_at"]

    # Same data on the next day: nothing to publish, checked_at moves on.
    copy_shards(tmp_path / "1" / "new", tmp_path / "2" / "previous")
    second = run_all(registry, tmp_path, m1, "2", force=False, only=["nist_csrc"])
    assert not second["changed"] and not (tmp_path / "2" / "index.sqlite").exists()
    m2 = second["manifest"]
    assert m2["release_tag"] == "index-1" and m2["index_sha256"] == m1["index_sha256"]
    assert m2["sources"]["nist_csrc"]["outcome"] == "unchanged"
    assert m2["sources"]["python_glossary"]["outcome"] == "not_due"
    assert m2["sources"]["python_glossary"]["checked_at"] == m1["sources"]["python_glossary"]["checked_at"]

    # force: rebuild and publish even though nothing changed.
    copy_shards(tmp_path / "1" / "new", tmp_path / "3" / "previous")
    third = run_all(registry, tmp_path, m2, "3", force=True)
    assert third["changed"] and third["manifest"]["release_tag"] == "index-3"


def test_failed_source_keeps_previous_shard(registry, tmp_path: Path, monkeypatch) -> None:
    m1 = run_all(registry, tmp_path, {}, "1")["manifest"]
    copy_shards(tmp_path / "1" / "new", tmp_path / "2" / "previous")
    monkeypatch.setattr(NistCsrc, "fetch", lambda self, raw_dir: (_ for _ in ()).throw(TimeoutError("timed out")))
    result = run_all(registry, tmp_path, m1, "2", force=True)
    assert result["sources"]["nist_csrc"]["outcome"] == "failed"
    assert (
        result["manifest"]["sources"]["nist_csrc"]["snapshot_version"] == m1["sources"]["nist_csrc"]["snapshot_version"]
    )
    # a failed source keeps its old checked_at, so it is due again tomorrow
    assert result["manifest"]["sources"]["nist_csrc"]["checked_at"] == m1["sources"]["nist_csrc"]["checked_at"]


def test_failed_source_without_previous_shard(registry, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(NistCsrc, "fetch", lambda self, raw_dir: (_ for _ in ()).throw(TimeoutError("timed out")))
    result = run_all(registry, tmp_path, {}, "1")
    assert result["changed"]
    assert sorted(result["manifest"]["sources"]) == ["python_glossary"]
    assert "not in the index" in result["sources"]["nist_csrc"]["message"]


def test_missing_status_of_a_due_source_is_a_failure(registry, tmp_path: Path) -> None:
    result = assemble(
        registry,
        due=["nist_csrc"],
        new_dir=tmp_path / "new",
        previous_dir=tmp_path / "previous",
        previous={},
        out=tmp_path / "index.sqlite",
        release_tag="x",
    )
    assert result["sources"]["nist_csrc"]["outcome"] == "failed"
    assert result["sources"]["python_glossary"]["outcome"] == "not_due"
    assert result["manifest"] == {"sources": {}} and not result["changed"]


def test_row_drop_guard(registry, tmp_path: Path) -> None:
    m1 = run_all(registry, tmp_path, {}, "1")["manifest"]
    copy_shards(tmp_path / "1" / "new", tmp_path / "2" / "previous")
    with sqlite3.connect(tmp_path / "2" / "previous" / shard_name("nist_csrc")) as conn:
        conn.execute("UPDATE sources SET row_count = 100")  # yesterday had 100, today 9
    result = run_all(registry, tmp_path, m1, "2", force=True)
    assert result["sources"]["nist_csrc"]["outcome"] == "rejected"
    assert "rows dropped 100 -> 9" in result["sources"]["nist_csrc"]["message"]
    assert result["manifest"]["sources"]["nist_csrc"]["row_count"] == 100  # the previous shard
    assert result["sources"]["nist_csrc"]["shard"] == str(tmp_path / "2" / "previous" / shard_name("nist_csrc"))


def test_golden_guard(registry, tmp_path: Path) -> None:
    registry["nist_csrc"] = replace(registry["nist_csrc"], golden=[{"query": "firewall", "expect": "firewall"}])
    result = run_all(registry, tmp_path, {}, "1")
    assert result["sources"]["nist_csrc"]["outcome"] == "rejected"
    assert result["sources"]["nist_csrc"]["message"].startswith("golden: 'firewall' did not find 'firewall'")


def test_refresh_all_sources(tmp_path: Path) -> None:
    """Every buildable source, offline: the fixtures pass their golden queries, alone and combined."""
    registry = load_registry(ROOT / "sources")
    result = run_all(registry, tmp_path, {}, "1")
    assert {sid: r["outcome"] for sid, r in result["sources"].items()} == dict.fromkeys(
        [
            "cncf_glossary",
            "ecma262",
            "git_glossary",
            "google_ml",
            "mdn",
            "mitre_cwe",
            "nist_csrc",
            "nist_dads",
            "owasp_cheatsheets",
            "owasp_genai",
            "postgresql_glossary",
            "python_glossary",
            "rfc_editor",
            "unicode_glossary",
            "webref",
        ],
        "built",
    )
    text = notice(registry, result["manifest"])
    assert text.startswith("# Notices for index-1")
    assert "## MITRE CWE (`mitre_cwe`)" in text and "reproduce MITRE's copyright designation" in text
    assert "- Attribution: Google, CC BY 4.0" in text


def test_cli_cycle(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "sources").symlink_to(ROOT / "sources")
    assert main(["plan"]) == 0
    assert main(["shard", "nist_csrc"]) == 0
    assert main(["shard", "python_glossary"]) == 0
    due = json.dumps(["nist_csrc", "python_glossary"])
    args = ["assemble", "--due", due, "--release-tag", "index-t", "--report", "r.json", "--summary", "s.md"]
    assert main([*args, "--notice", "NOTICE.md"]) == 0
    assert read_json(tmp_path / "manifest" / "sources.json")["release_tag"] == "index-t"
    assert read_json(tmp_path / "r.json")["changed"] is True
    assert "| nist_csrc | built | 9 |" in (tmp_path / "s.md").read_text()
    assert "## NIST CSRC Glossary (`nist_csrc`)" in (tmp_path / "NOTICE.md").read_text()

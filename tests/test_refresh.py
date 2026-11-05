import json
import shutil
import sqlite3
import subprocess
import urllib.error
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml
from conftest import ROOT

from terminology_indexes.build import BuildError
from terminology_indexes.cli import main
from terminology_indexes.ingest.html_page import RobotsDenied
from terminology_indexes.ingest.nist_csrc import NistCsrc
from terminology_indexes.model import load_registry, parse_period
from terminology_indexes.refresh import GRACE, assemble, notice, plan, read_json, refresh_source, shard_name, summary

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


def run_all(registry, tmp_path: Path, previous: dict, name: str, at: datetime = NOW, **kw) -> dict:
    """One whole refresh: plan, a shard job per due source, assemble."""
    due = plan(registry, previous, at=at, **kw)
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
        at=at,
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
    assert status["temporary"] is False
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
        at=NOW,
    )
    assert result["sources"]["nist_csrc"]["outcome"] == "failed"
    assert result["sources"]["nist_csrc"]["alert"]  # the job died; nothing says it was only the site
    assert result["sources"]["python_glossary"]["outcome"] == "not_due"
    assert result["manifest"] == {"sources": {}} and not result["changed"]


def fail_nist(monkeypatch, error: Exception) -> None:
    def fetch(self, raw_dir):
        raise error

    monkeypatch.setattr(NistCsrc, "fetch", fetch)


@pytest.mark.parametrize(
    "error",
    [
        urllib.error.URLError(ConnectionRefusedError(111, "Connection refused")),
        TimeoutError("timed out"),
        urllib.error.HTTPError("https://x", 503, "Service Unavailable", {}, None),
        urllib.error.HTTPError("https://x", 429, "Too Many Requests", {}, None),
    ],
    ids=["refused", "timeout", "503", "429"],
)
def test_temporary_failure_alerts_only_after_the_grace(registry, tmp_path: Path, monkeypatch, error) -> None:
    m1 = run_all(registry, tmp_path, {}, "1")["manifest"]
    copy_shards(tmp_path / "1" / "new", tmp_path / "2" / "previous")
    fail_nist(monkeypatch, error)
    # P1D source: last checked a day before NOW, so it has been due since NOW
    m1["sources"]["nist_csrc"]["checked_at"] = (NOW - timedelta(days=1)).isoformat()
    m1["sources"]["python_glossary"]["checked_at"] = NOW.isoformat()

    quiet = run_all(registry, tmp_path, m1, "2", at=NOW + GRACE - timedelta(hours=1))["sources"]["nist_csrc"]
    assert quiet["outcome"] == "failed" and not quiet["alert"]
    assert "failing since" not in quiet["message"]

    late = run_all(registry, tmp_path, m1, "2", at=NOW + GRACE)["sources"]["nist_csrc"]
    assert late["outcome"] == "failed" and late["alert"]
    assert f"failing since {NOW.date()}" in late["message"]


@pytest.mark.parametrize(
    "error",
    [
        urllib.error.HTTPError("https://x", 403, "Forbidden", {}, None),
        urllib.error.HTTPError("https://x", 404, "Not Found", {}, None),
        RobotsDenied("disallowed by robots.txt"),
        ValueError("unknown schema"),
    ],
    ids=["403", "404", "robots", "parse"],
)
def test_failure_that_needs_a_person_alerts_at_once(registry, tmp_path: Path, monkeypatch, error) -> None:
    m1 = run_all(registry, tmp_path, {}, "1")["manifest"]
    copy_shards(tmp_path / "1" / "new", tmp_path / "2" / "previous")
    fail_nist(monkeypatch, error)
    assert run_all(registry, tmp_path, m1, "2", at=datetime.now(UTC), force=True)["sources"]["nist_csrc"]["alert"]


def test_temporary_failure_without_a_shard_alerts_at_once(registry, tmp_path: Path, monkeypatch) -> None:
    fail_nist(monkeypatch, TimeoutError("timed out"))
    assert run_all(registry, tmp_path, {}, "1")["sources"]["nist_csrc"]["alert"]


def test_summary_marks_quiet_failures(registry, tmp_path: Path, monkeypatch) -> None:
    m1 = run_all(registry, tmp_path, {}, "1")["manifest"]
    copy_shards(tmp_path / "1" / "new", tmp_path / "2" / "previous")
    fail_nist(monkeypatch, TimeoutError("timed out"))
    result = run_all(registry, tmp_path, m1, "2", at=datetime.now(UTC), force=True)
    assert "| nist_csrc | failed (temporary) | 9 |" in summary(result)


def test_rejected_shard_alerts_at_once(registry, tmp_path: Path) -> None:
    registry["nist_csrc"] = replace(registry["nist_csrc"], golden=[{"query": "firewall", "expect": "firewall"}])
    assert run_all(registry, tmp_path, {}, "1")["sources"]["nist_csrc"]["alert"]


def run_step(tmp_path: Path, name: str, gh: str, manifest: dict | None = None) -> subprocess.CompletedProcess:
    """A step of the combine job in ``refresh.yml``, as Actions runs it, with a stand-in for ``gh``."""
    if not (shutil.which("jq") and shutil.which("zstd")):
        pytest.skip("needs jq and zstd")
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "refresh.yml").read_text(encoding="utf-8"))
    step = next(s for s in workflow["jobs"]["combine"]["steps"] if s.get("name") == name)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "gh").write_text(f"#!/bin/sh\n{gh}\n")
    (bin_dir / "gh").chmod(0o755)
    (tmp_path / "new").mkdir()
    if manifest is not None:
        (tmp_path / "manifest").mkdir()
        (tmp_path / "manifest" / "sources.json").write_text(json.dumps(manifest))
    return subprocess.run(
        ["bash", "-eo", "pipefail", "-c", step["run"]],
        cwd=tmp_path,
        env={"PATH": f"{bin_dir}:/usr/bin:/bin"},
        capture_output=True,
        text=True,
    )


def test_issues_step_follows_alert(tmp_path: Path) -> None:
    def source(outcome: str, alert: bool) -> dict:
        return {"outcome": outcome, "alert": alert, "message": f"{outcome} message"}

    report = {
        "quiet": source("failed", False),
        "quiet_open": source("failed", False),
        "broken": source("failed", True),
        "refused": source("rejected", True),
        "recovered": source("unchanged", False),
    }
    (tmp_path / "report.json").write_text(json.dumps({"sources": report}))
    gh = """echo "$*" >> gh.log
case "$*" in "issue list --label source:quiet_open "*|"issue list --label source:recovered "*) echo 7 ;; esac"""
    done = run_step(tmp_path, "Issues", gh)
    assert done.returncode == 0, done.stderr
    calls = [c for c in (tmp_path / "gh.log").read_text().splitlines() if not c.startswith("issue list")]
    assert not [c for c in calls if "quiet" in c or c.startswith("issue comment")]
    assert any(c.startswith("issue create --title broken: failed") for c in calls)
    assert any(c.startswith("issue create --title refused: rejected") for c in calls)
    assert any(c.startswith("issue close 7") for c in calls)


def run_previous_release_step(tmp_path: Path, gh: str, manifest: dict | None) -> subprocess.CompletedProcess:
    return run_step(tmp_path, "Previous release", gh, manifest)


def test_previous_release_download_failure_stops_the_job(tmp_path: Path) -> None:
    done = run_previous_release_step(tmp_path, "exit 1", {"release_tag": "index-1", "sources": {}})
    assert done.returncode != 0 and "::error::" in done.stdout and "index-1" in done.stdout


@pytest.mark.parametrize("manifest", [None, {"sources": {}}], ids=["no-manifest", "no-tag"])
def test_first_run_goes_on_without_a_previous_release(tmp_path: Path, manifest) -> None:
    done = run_previous_release_step(tmp_path, "exit 1", manifest)
    assert done.returncode == 0 and "::warning::" in done.stdout


def test_previous_release_is_downloaded_and_unpacked(tmp_path: Path) -> None:
    gh = 'echo "$@" > gh.args; echo shard | zstd -q -o previous/shard-a.sqlite.zst'
    done = run_previous_release_step(tmp_path, gh, {"release_tag": "index-1", "sources": {}})
    assert done.returncode == 0, done.stderr
    assert (tmp_path / "gh.args").read_text().startswith("release download index-1 ")
    assert (tmp_path / "previous" / "shard-a.sqlite").read_text() == "shard\n"


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
            "etymonline",
            "eurovoc",
            "git_glossary",
            "google_ml",
            "iate",
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
            "wiktionary",
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

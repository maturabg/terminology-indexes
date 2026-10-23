"""Nightly refresh: which sources are due, one shard per source, then the release.

``refresh.yml`` runs ``plan`` once, ``refresh_source`` once per due source (a
matrix job each), and ``assemble`` once over all of their outputs. Every step
reads and writes the same manifest format as ``build.manifest``, with two more
fields per source: ``checked_at`` (last successful fetch, changed or not) and
``outcome`` of the last run.
"""

import json
import logging
import sqlite3
from collections.abc import Iterable
from datetime import datetime, timedelta
from pathlib import Path

from terminology_indexes.build import BuildError, build_shard, combine, manifest, now
from terminology_indexes.ingest import ADAPTERS, get_adapter
from terminology_indexes.model import Source
from terminology_indexes.providers import load_providers

log = logging.getLogger(__name__)

# outcome of a source in one run
BUILT = "built"  # new shard, passed the guards
UNCHANGED = "unchanged"  # raw data has the same SHA-256 as the shard in the previous release
NOT_DUE = "not_due"
FAILED = "failed"  # fetch or parse raised; the previous shard stays
REJECTED = "rejected"  # a guard refused the new shard; the previous shard stays
PROBLEMS = frozenset({FAILED, REJECTED})

# The cron does not fire at the same minute every day; a P1D source checked
# yesterday a bit later than today's run must still be due.
MAX_SLACK = timedelta(hours=12)


def shard_name(source_id: str) -> str:
    return f"shard-{source_id}.sqlite"


def status_name(source_id: str) -> str:
    return f"status-{source_id}.json"


def read_json(path: Path | None) -> dict:
    if path is None or not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def buildable(registry: dict[str, Source]) -> dict[str, Source]:
    """Sources the refresh builds: ``mode: index``, ``status: active``, with an adapter."""
    return {sid: s for sid, s in registry.items() if s.mode == "index" and s.status == "active" and sid in ADAPTERS}


def is_due(source: Source, previous: dict | None, at: datetime) -> bool:
    last = (previous or {}).get("checked_at") or (previous or {}).get("fetched_at")
    if not last or source.refresh is None:
        return True
    return at - datetime.fromisoformat(last) >= source.refresh - min(MAX_SLACK, source.refresh / 2)


def plan(
    registry: dict[str, Source],
    previous: dict,
    *,
    at: datetime,
    only: Iterable[str] | None = None,
    force: bool = False,
) -> list[str]:
    """Ids of the sources to fetch now. ``only`` and ``force`` make sources due regardless of schedule."""
    sources = buildable(registry)
    if only:
        only = list(only)
        if bad := [s for s in only if s not in sources]:
            raise BuildError(f"not buildable: {bad}; buildable: {sorted(sources)}")
        return sorted(only)
    seen = previous.get("sources", {})
    return sorted(sid for sid, s in sources.items() if force or is_due(s, seen.get(sid), at))


def refresh_source(source: Source, raw_dir: Path, shards_dir: Path, previous: dict, *, force: bool = False) -> dict:
    """Fetch and parse one source into ``shards_dir``; write and return its status.

    Never raises for a source error: a broken site is a ``failed`` status, not a failed job.
    """
    status: dict = {"source": source.id, "checked_at": now()}
    try:
        adapter = get_adapter(source)
        snapshot = adapter.fetch(raw_dir)
        status["raw_sha256"] = snapshot.sha256
        if not force and snapshot.sha256 == previous.get("sources", {}).get(source.id, {}).get("raw_sha256"):
            status["outcome"] = UNCHANGED
        else:
            status["rows"] = build_shard(source, snapshot, shards_dir / shard_name(source.id))
            status["outcome"] = BUILT
    except Exception as e:
        log.exception("%s failed", source.id)
        status |= {"outcome": FAILED, "message": f"{type(e).__name__}: {e}"}
    write_json(shards_dir / status_name(source.id), status)
    return status


def shard_rows(shard: Path) -> int:
    with sqlite3.connect(f"file:{shard}?mode=ro", uri=True) as conn:
        return conn.execute("SELECT sum(row_count) FROM sources").fetchone()[0] or 0


def golden_failures(source: Source, index: Path) -> list[str]:
    """``golden`` queries from the registry whose expected ``external_id`` is not found."""
    failures = []
    with load_providers(index, env={}, live=False) as registry:
        provider = registry.providers.get(source.id)
        for g in source.golden:
            found = [c.external_id for c in provider.search(g["query"], limit=10)] if provider else []
            if g["expect"] not in found:
                failures.append(f"{g['query']!r} did not find {g['expect']!r}")
    return failures


def guard(source: Source, new: Path, previous: Path | None) -> str | None:
    """Why ``new`` must not replace ``previous``, or ``None`` if it may."""
    if previous is not None and source.max_row_drop is not None:
        before, after = shard_rows(previous), shard_rows(new)
        if before and after < before * (1 - source.max_row_drop):
            return f"rows dropped {before} -> {after} (max_row_drop {source.max_row_drop})"
    if failures := golden_failures(source, new):
        return "golden: " + "; ".join(failures)
    return None


def assemble(
    registry: dict[str, Source],
    *,
    due: Iterable[str],
    new_dir: Path,
    previous_dir: Path,
    previous: dict,
    out: Path,
    release_tag: str,
    force: bool = False,
) -> dict:
    """Pick one shard per source, combine them into ``out`` if anything changed.

    Returns ``{"changed": bool, "manifest": {...}, "sources": {id: {"outcome", "message", "shard"}}}``;
    ``shard`` is the file that went into the index (the release publishes exactly these).
    ``manifest`` is the new one if ``changed``, else the previous one with fresh ``checked_at``.
    """
    sources = buildable(registry)
    due = set(due)
    seen = previous.get("sources", {})
    chosen: dict[str, Path] = {}
    report: dict[str, dict] = {}
    for sid, source in sorted(sources.items()):
        status = read_json(new_dir / status_name(sid))
        new, old = new_dir / shard_name(sid), previous_dir / shard_name(sid)
        old = old if old.exists() else None
        outcome, message = status.get("outcome"), status.get("message", "")
        if outcome is None:
            outcome, message = (FAILED, "no status from the fetch job") if sid in due else (NOT_DUE, "")
        if outcome == BUILT:
            if not new.exists():
                outcome, message = FAILED, "status says built, shard is missing"
            elif problem := guard(source, new, old):
                outcome, message = REJECTED, problem
            else:
                chosen[sid] = new
        if sid not in chosen and old is not None:
            chosen[sid] = old
        elif sid not in chosen:
            message = (message + "; " if message else "") + "no previous shard: source is not in the index"
        checked_at = status["checked_at"] if outcome in (BUILT, UNCHANGED) else seen.get(sid, {}).get("checked_at")
        shard = str(chosen[sid]) if sid in chosen else None
        report[sid] = {"outcome": outcome, "message": message, "checked_at": checked_at, "shard": shard}

    rebuilt = any(r["outcome"] == BUILT for r in report.values())
    changed = force or rebuilt or set(chosen) != set(seen)
    if changed:
        combine(chosen.values(), out, release_tag)
        if failures := [f"{sid}: {f}" for sid, s in sources.items() if sid in chosen for f in golden_failures(s, out)]:
            raise BuildError("golden queries failed on the combined index: " + "; ".join(failures))
        result = manifest(out)
    else:
        result = json.loads(json.dumps(previous))
    for sid, entry in result.setdefault("sources", {}).items():
        entry["checked_at"] = report.get(sid, {}).get("checked_at") or entry.get("checked_at") or entry["fetched_at"]
        entry["outcome"] = report.get(sid, {}).get("outcome", NOT_DUE)
    return {"changed": changed, "manifest": result, "sources": report}


def notice(registry: dict[str, Source], manifest: dict) -> str:
    """``NOTICE.md`` of a release: attribution and license of every source in the index."""
    lines = [
        f"# Notices for {manifest.get('release_tag') or 'index.sqlite'}",
        "",
        "The index holds titles, URLs and, where the license allows, short snippets of these sources.",
    ]
    for sid in sorted(manifest.get("sources", {})):
        source = registry.get(sid)
        if source is None:
            continue
        license_ = source.raw.get("license") or {}
        lines += [
            "",
            f"## {source.name} (`{sid}`)",
            "",
            f"- Attribution: {source.attribution}",
            f"- License: {source.license_class}, {license_.get('url') or '—'}",
            f"- Snapshot: {manifest['sources'][sid].get('snapshot_version', '—')}",
        ]
        if text := (source.raw.get("notice") or "").strip():
            lines += ["", text]
    return "\n".join(lines) + "\n"


def summary(result: dict) -> str:
    """Markdown for the job summary."""
    m = result["manifest"]
    head = (
        f"Release `{m.get('release_tag')}` published."
        if result["changed"]
        else f"Nothing changed; latest release stays `{m.get('release_tag')}`."
    )
    lines = [head, "", "| source | outcome | rows | snapshot | message |", "| --- | --- | --- | --- | --- |"]
    for sid, r in result["sources"].items():
        entry = m["sources"].get(sid, {})
        lines.append(
            f"| {sid} | {r['outcome']} | {entry.get('row_count', '—')} | {entry.get('snapshot_version', '—')}"
            f" | {r['message'].replace('|', '\\|')} |"
        )
    return "\n".join(lines) + "\n"

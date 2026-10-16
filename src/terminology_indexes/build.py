"""Build per-source shards and combine them into ``index.sqlite``."""

import json
import sqlite3
from collections.abc import Iterable
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path

from terminology_indexes.ingest import get_adapter
from terminology_indexes.ingest.base import RawSnapshot, sha256_file
from terminology_indexes.model import SCHEMA_VERSION, Entry, Source
from terminology_indexes.normalize import NORM_VERSION, normalize_term, term_key

ENTRY_COLS = "source, external_id, url, title, kind, lang, status, replaced_by, snippet, extra"
SCHEMA = files("terminology_indexes").joinpath("schema.sql").read_text(encoding="utf-8")


class BuildError(RuntimeError):
    pass


def now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def create_db(path: Path, meta: dict[str, str]) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    base = {"schema_version": str(SCHEMA_VERSION), "norm_version": str(NORM_VERSION), "built_at": now()}
    conn.executemany("INSERT INTO meta VALUES (?, ?)", (base | meta).items())
    return conn


def read_meta(conn: sqlite3.Connection, schema: str = "main") -> dict[str, str]:
    return dict(conn.execute(f"SELECT key, value FROM {schema}.meta"))


def write_entries(conn: sqlite3.Connection, source: Source, entries: Iterable[Entry]) -> int:
    count = 0
    for e in entries:
        cur = conn.execute(
            f"INSERT INTO entries ({ENTRY_COLS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                source.id,
                e.external_id,
                e.url,
                e.title,
                e.kind,
                e.lang,
                e.status,
                e.replaced_by,
                source.clip_snippet(e.snippet),
                json.dumps(e.extra, ensure_ascii=False) if e.extra else None,
            ),
        )
        conn.executemany(
            "INSERT INTO labels (entry_id, label, label_norm, label_key, lang, label_type) VALUES (?, ?, ?, ?, ?, ?)",
            [
                (cur.lastrowid, l.label, normalize_term(l.label), term_key(l.label), l.lang, l.label_type)
                for l in e.labels
            ],
        )
        count += 1
    return count


def build_shard(source: Source, snapshot: RawSnapshot, out: Path) -> int:
    """Parse ``snapshot`` into ``out`` (``shard-<id>.sqlite``); return the row count."""
    adapter = get_adapter(source)
    conn = create_db(out, {"shard": source.id})
    try:
        with conn:
            rows = write_entries(conn, source, adapter.parse(snapshot))
            if rows == 0:
                raise BuildError(f"{source.id}: parser returned no entries")
            conn.execute(
                "INSERT INTO sources VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    source.id,
                    snapshot.snapshot_version,
                    now(),
                    snapshot.sha256,
                    rows,
                    source.license_class,
                    source.attribution,
                ),
            )
            conn.execute("INSERT INTO labels_fts(labels_fts) VALUES ('rebuild')")
        conn.execute("VACUUM")
    except BaseException:
        conn.close()
        out.unlink(missing_ok=True)
        raise
    conn.close()
    return rows


def fetch_and_build(source: Source, raw_dir: Path, shards_dir: Path) -> int:
    snapshot = get_adapter(source).fetch(raw_dir)
    return build_shard(source, snapshot, shards_dir / f"shard-{source.id}.sqlite")


def combine(shards: Iterable[Path], out: Path, release_tag: str = "") -> dict[str, int]:
    """Merge shards into one index; entry ids are reassigned."""
    conn = create_db(out, {"release_tag": release_tag})
    counts: dict[str, int] = {}
    try:
        for shard in sorted(shards):
            conn.execute("ATTACH DATABASE ? AS s", (str(shard),))
            meta = read_meta(conn, "s")
            if meta.get("schema_version") != str(SCHEMA_VERSION) or meta.get("norm_version") != str(NORM_VERSION):
                raise BuildError(
                    f"{shard.name}: schema/norm {meta.get('schema_version')}/{meta.get('norm_version')},"
                    f" expected {SCHEMA_VERSION}/{NORM_VERSION}; full rebuild required"
                )
            with conn:
                conn.execute("INSERT INTO sources SELECT * FROM s.sources")
                conn.execute(f"INSERT INTO entries ({ENTRY_COLS}) SELECT {ENTRY_COLS} FROM s.entries")
                conn.execute(
                    "INSERT INTO labels (entry_id, label, label_norm, label_key, lang, label_type)"
                    " SELECT e.id, l.label, l.label_norm, l.label_key, l.lang, l.label_type"
                    " FROM s.labels l JOIN s.entries se ON se.id = l.entry_id"
                    " JOIN entries e ON e.source = se.source AND e.external_id = se.external_id"
                )
            counts.update(conn.execute("SELECT source, row_count FROM s.sources"))
            conn.execute("DETACH DATABASE s")
        if not counts:
            raise BuildError("no shards to combine")
        with conn:
            conn.execute("INSERT INTO labels_fts(labels_fts) VALUES ('rebuild')")
            conn.execute("INSERT INTO labels_fts(labels_fts) VALUES ('optimize')")
        conn.execute("VACUUM")
    except BaseException:
        conn.close()
        out.unlink(missing_ok=True)
        raise
    conn.close()
    return counts


def manifest(index: Path) -> dict:
    """Small JSON description of a built index, for the release and the repo."""
    conn = sqlite3.connect(f"file:{index}?mode=ro", uri=True)
    try:
        cols = ["snapshot_version", "fetched_at", "raw_sha256", "row_count", "license"]
        sources = {
            row[0]: dict(zip(cols, row[1:], strict=True))
            for row in conn.execute(f"SELECT source, {', '.join(cols)} FROM sources ORDER BY source")
        }
        return {**read_meta(conn), "index_sha256": sha256_file(index), "sources": sources}
    finally:
        conn.close()

"""``IndexProvider``: one per source present in ``index.sqlite``."""

import sqlite3
from pathlib import Path

from terminology_indexes.contract import Candidate, CheckResult, LinkRecord
from terminology_indexes.model import check_schema_version
from terminology_indexes.search import search


def open_index(path: Path | str) -> sqlite3.Connection:
    """Open read-only and refuse an index with another ``schema_version``."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
        check_schema_version(row and row[0], path)
    except BaseException:
        conn.close()
        raise
    return conn


class IndexProvider:
    def __init__(self, conn: sqlite3.Connection, source: str, snapshot_version: str) -> None:
        self.conn = conn
        self.id = source
        self.snapshot_version = snapshot_version

    def __repr__(self) -> str:
        return f"IndexProvider({self.id!r}, {self.snapshot_version!r})"

    def search(self, query: str, *, lang: str | None = None, limit: int = 5) -> list[Candidate]:
        return [
            Candidate(
                source=h.source,
                external_id=h.external_id,
                url=h.url,
                title=h.title,
                kind=h.kind,
                matched_label=h.matched_label,
                match=h.match,
                snippet=h.snippet,
                snapshot_version=self.snapshot_version,
            )
            for h in search(self.conn, query, lang=lang, source=self.id, limit=limit)
        ]

    def _entry(self, external_id: str) -> tuple[str, str, str | None] | None:
        return self.conn.execute(
            "SELECT url, status, replaced_by FROM entries WHERE source = ? AND external_id = ?",
            (self.id, external_id),
        ).fetchone()

    def check(self, link: LinkRecord) -> CheckResult:
        # The shard in the index is always one that passed the guards (a rejected
        # shard is replaced by the previous one), so a missing id means dead.
        row = self._entry(link.external_id)
        if row is None:
            return CheckResult("dead", reason=f"not in {self.id} {self.snapshot_version}")
        url, status, replaced_by = row
        if status == "active":
            if url == link.url:
                return CheckResult("ok")
            return CheckResult("moved", new_url=url, reason="url changed")
        if replaced_by and (new := self._entry(replaced_by)) and new[1] == "active":
            return CheckResult("moved", new_url=new[0], reason=f"{status}, replaced by {replaced_by}")
        return CheckResult("dead", reason=f"{status} without an active replacement")

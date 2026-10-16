"""Lookup over ``index.sqlite``: exact key, then FTS. Only ``active`` entries.

``IndexProvider`` (``providers/index.py``) wraps this into the ``Provider`` contract.
"""

import sqlite3
from dataclasses import dataclass

from terminology_indexes.normalize import normalize_term, term_key


@dataclass(frozen=True)
class Hit:
    source: str
    external_id: str
    url: str
    title: str
    kind: str
    matched_label: str
    match: str  # exact | alias | fts
    snippet: str | None


_SELECT = (
    "SELECT e.source, e.external_id, e.url, e.title, e.kind, l.label, l.label_type, e.snippet"
    " FROM labels l JOIN entries e ON e.id = l.entry_id"
)


def _fts_query(text: str) -> str:
    """Quote every token so user input is never FTS syntax; prefix-match the last one."""
    tokens = [t for t in normalize_term(text).replace("-", " ").split() if t]
    if not tokens:
        return ""
    quoted = ['"' + t.replace('"', '""') + '"' for t in tokens]
    quoted[-1] += "*"
    return " ".join(quoted)


def search(
    conn: sqlite3.Connection, query: str, *, lang: str | None = None, source: str | None = None, limit: int = 5
) -> list[Hit]:
    where_sql, where_args = " AND e.status = 'active'", []
    if lang:
        where_sql += " AND (l.lang = ? OR l.lang IS NULL)"
        where_args.append(lang)
    if source:
        where_sql += " AND e.source = ?"
        where_args.append(source)
    hits: dict[tuple[str, str], Hit] = {}

    def add(rows, match_of) -> None:
        for src, ext, url, title, kind, label, label_type, snippet in rows:
            if (src, ext) not in hits and len(hits) < limit:
                hits[src, ext] = Hit(src, ext, url, title, kind, label, match_of(label_type), snippet)

    if key := term_key(query):
        rows = conn.execute(
            f"{_SELECT} WHERE l.label_key = ?{where_sql} ORDER BY l.label_type != 'pref', e.id",
            [key, *where_args],
        )
        add(rows, lambda t: "exact" if t == "pref" else "alias")
    if len(hits) < limit and (fts := _fts_query(query)):
        rows = conn.execute(
            f"{_SELECT} JOIN labels_fts f ON f.rowid = l.rowid"
            f" WHERE labels_fts MATCH ?{where_sql} ORDER BY bm25(labels_fts) LIMIT ?",
            [fts, *where_args, limit * 4],
        )
        add(rows, lambda _t: "fts")
    return list(hits.values())

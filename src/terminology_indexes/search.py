"""Minimal lookup over ``index.sqlite``: exact key, then FTS.

The ``Provider`` contract (iteration 2) wraps this.
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


def search(conn: sqlite3.Connection, query: str, *, lang: str | None = None, limit: int = 5) -> list[Hit]:
    lang_sql, lang_args = (" AND (l.lang = ? OR l.lang IS NULL)", [lang]) if lang else ("", [])
    hits: dict[tuple[str, str], Hit] = {}

    def add(rows, match_of) -> None:
        for source, ext, url, title, kind, label, label_type, snippet in rows:
            if (source, ext) not in hits and len(hits) < limit:
                hits[source, ext] = Hit(source, ext, url, title, kind, label, match_of(label_type), snippet)

    if key := term_key(query):
        rows = conn.execute(
            f"{_SELECT} WHERE l.label_key = ?{lang_sql} ORDER BY l.label_type != 'pref', e.id",
            [key, *lang_args],
        )
        add(rows, lambda t: "exact" if t == "pref" else "alias")
    if len(hits) < limit and (fts := _fts_query(query)):
        rows = conn.execute(
            f"{_SELECT} JOIN labels_fts f ON f.rowid = l.rowid"
            f" WHERE labels_fts MATCH ?{lang_sql} ORDER BY bm25(labels_fts) LIMIT ?",
            [fts, *lang_args, limit * 4],
        )
        add(rows, lambda _t: "fts")
    return list(hits.values())

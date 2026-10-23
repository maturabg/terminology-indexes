"""``load_providers`` and the ``Registry`` that enrichment talks to."""

import logging
import os
import sqlite3
from collections.abc import Iterable, Mapping
from dataclasses import replace
from importlib import import_module
from pathlib import Path

from terminology_indexes.contract import MATCH_RANK, Candidate, CheckResult, LinkRecord, Provider
from terminology_indexes.providers.index import IndexProvider, open_index

log = logging.getLogger(__name__)

# With a translation, each side looks this deep for an entry both reach.
BILINGUAL_POOL = 20

# Live providers (iteration 7): source id -> "module:Class". A class may set
# ``secret_env``; without that variable in ``env`` it is not registered.
# The constructor takes ``env``.
LIVE_PROVIDERS: dict[str, str] = {}


class Registry:
    def __init__(self, providers: Iterable[Provider], conn: sqlite3.Connection | None = None) -> None:
        self.providers: dict[str, Provider] = {p.id: p for p in providers}
        self._conn = conn

    def __enter__(self) -> Registry:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def _select(self, sources: Iterable[str] | None) -> list[Provider]:
        if sources is None:
            return list(self.providers.values())
        sources = list(sources)
        if unknown := [s for s in sources if s not in self.providers]:
            raise ValueError(f"unknown source(s) {unknown}; available: {sorted(self.providers)}")
        return [self.providers[s] for s in sources]

    def search_all(
        self,
        query: str,
        *,
        translation: str | None = None,
        lang: str | None = None,
        translation_lang: str = "bg",
        sources: Iterable[str] | None = None,
        limit: int = 10,
        per_source: int = 3,
    ) -> list[Candidate]:
        """Exact ``label_key`` > alias > FTS; each source contributes at most ``per_source``.

        Within one match type, sources interleave by their own rank, so a large
        source cannot push the others out.

        ``translation`` (the BG side of the dictionary row) is the bilingual bonus:
        an entry that both ``query`` and ``translation`` find moves up one match type
        and ahead of its ties, and carries the translation's label in ``also_matched``.
        An exact match on both sides comes first of all.
        """
        ranked: list[tuple[int, bool, int, Candidate]] = []
        for provider in self._select(sources):
            try:
                found = provider.search(query, lang=lang, limit=BILINGUAL_POOL if translation else per_source)
                both = {}
                if translation:
                    for c in provider.search(translation, lang=translation_lang, limit=BILINGUAL_POOL):
                        both.setdefault(c.external_id, c.matched_label)
            except Exception:
                log.warning("search failed in %s", provider.id, exc_info=True)
                continue
            scored = sorted(
                (MATCH_RANK[c.match] - (c.external_id in both), c.external_id not in both, pos, c)
                for pos, c in enumerate(found)
            )
            for pos, (rank, single, _, c) in enumerate(scored[:per_source]):
                ranked.append((rank, single, pos, c if single else replace(c, also_matched=both[c.external_id])))
        ranked.sort(key=lambda r: r[:3])
        return [c for *_, c in ranked[:limit]]

    def check(self, link: LinkRecord) -> CheckResult:
        provider = self.providers.get(link.source)
        if provider is None:
            return CheckResult("unknown", reason=f"no provider for {link.source!r}")
        return provider.check(link)


def _live_providers(env: Mapping[str, str]) -> list[Provider]:
    providers = []
    for source_id, target in LIVE_PROVIDERS.items():
        module, _, name = target.partition(":")
        cls = getattr(import_module(module), name)
        secret = getattr(cls, "secret_env", None)
        if secret and not env.get(secret):
            log.info("%s: %s not set, not registered", source_id, secret)
            continue
        providers.append(cls(env))
    return providers


def load_providers(index_path: Path | str | None, *, env: Mapping[str, str] | None = None) -> Registry:
    """One ``IndexProvider`` per source in the index, plus the live providers ``env`` allows.

    Raises ``IndexVersionError`` if the index has another ``schema_version``.
    """
    env = os.environ if env is None else env
    providers: list[Provider] = []
    conn = None
    if index_path is not None:
        conn = open_index(index_path)
        rows = conn.execute("SELECT source, snapshot_version FROM sources ORDER BY source").fetchall()
        release = dict(conn.execute("SELECT key, value FROM meta")).get("release_tag") or ""
        providers += [IndexProvider(conn, s, release or v) for s, v in rows]
    return Registry(providers + _live_providers(env), conn)

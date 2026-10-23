"""``load_providers`` and the ``Registry`` that enrichment talks to."""

import logging
import os
import sqlite3
from collections.abc import Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from importlib import import_module
from pathlib import Path

from terminology_indexes.contract import MATCH_RANK, Candidate, CheckResult, LinkRecord, Provider
from terminology_indexes.providers.index import IndexProvider, open_index

log = logging.getLogger(__name__)

# With a translation, each side looks this deep for an entry both reach.
BILINGUAL_POOL = 20

# Live providers: source id -> "module:Class". A class may set ``secret_env``;
# without that variable in ``env`` it is not registered. The constructor takes ``env``.
LIVE_PROVIDERS: dict[str, str] = {
    "eurlex": "terminology_indexes.providers.eurlex:Eurlex",
    "lexit": "terminology_indexes.providers.lexit:Lexit",
    "w3c": "terminology_indexes.providers.w3c:W3c",
    "wikidata": "terminology_indexes.providers.wikidata:Wikidata",
}
# Index sources whose ``check`` goes live: an ``IndexProvider`` subclass.
INDEX_PROVIDERS: dict[str, str] = {
    "wiktionary": "terminology_indexes.providers.wiktionary:WiktionaryProvider",
}


def _load(target: str) -> type:
    module, _, name = target.partition(":")
    return getattr(import_module(module), name)


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
        selected = self._select(sources)

        def hits_of(provider: Provider) -> list[tuple[int, bool, int, Candidate]]:
            try:
                found = provider.search(query, lang=lang, limit=BILINGUAL_POOL if translation else per_source)
                both = {}
                if translation:
                    for c in provider.search(translation, lang=translation_lang, limit=BILINGUAL_POOL):
                        both.setdefault(c.external_id, c.matched_label)
            except Exception:
                log.warning("search failed in %s", provider.id, exc_info=True)
                return []
            scored = sorted(
                (MATCH_RANK[c.match] - (c.external_id in both), c.external_id not in both, pos, c)
                for pos, c in enumerate(found)
            )
            return [
                (rank, single, pos, c if single else replace(c, also_matched=both[c.external_id]))
                for pos, (rank, single, _, c) in enumerate(scored[:per_source])
            ]

        # Live providers wait on their APIs: ask them all at once. The index ones share
        # one SQLite connection and stay in this thread.
        live = [p for p in selected if getattr(p, "live", False)]
        with ThreadPoolExecutor(max_workers=len(live) or 1) as pool:
            pending = {p.id: pool.submit(hits_of, p) for p in live}
            by_source = {p.id: hits_of(p) for p in selected if p.id not in pending}
            by_source |= {sid: f.result() for sid, f in pending.items()}
        ranked = [r for p in selected for r in by_source[p.id]]
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
        cls = _load(target)
        secret = getattr(cls, "secret_env", None)
        if secret and not env.get(secret):
            log.info("%s: %s not set, not registered", source_id, secret)
            continue
        providers.append(cls(env))
    return providers


def load_providers(
    index_path: Path | str | None, *, env: Mapping[str, str] | None = None, live: bool = True
) -> Registry:
    """One ``IndexProvider`` per source in the index, plus the live providers ``env`` allows.

    ``live=False`` keeps to the index: no live providers, and no ``check`` goes to an API.
    Raises ``IndexVersionError`` if the index has another ``schema_version``.
    """
    env = os.environ if env is None else env
    providers: list[Provider] = []
    conn = None
    if index_path is not None:
        conn = open_index(index_path)
        rows = conn.execute("SELECT source, snapshot_version FROM sources ORDER BY source").fetchall()
        release = dict(conn.execute("SELECT key, value FROM meta")).get("release_tag") or ""
        for source, version in rows:
            cls = _load(INDEX_PROVIDERS[source]) if live and source in INDEX_PROVIDERS else IndexProvider
            providers.append(cls(conn, source, release or version))
    return Registry(providers + (_live_providers(env) if live else []), conn)

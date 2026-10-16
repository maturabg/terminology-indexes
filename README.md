# terminology-indexes

Буферен индекс (`index.sqlite`, SQLite + FTS5) и адаптери на източниците за en2bg техническия речник. План: `TODO.md`, решения: `docs/decisions.md`.

## Локално

```sh
uv sync
uv run idx build --source python_glossary   # raw/ → shards/shard-<id>.sqlite → index.sqlite
uv run idx query "decorator"                # search_all: exact > alias > FTS, лимит по източник
uv run idx check python_glossary decorator https://docs.python.org/3/glossary.html#term-decorator
uv run idx fetch --dest dl                  # последният release → dl/index.sqlite (проверен SHA-256)
uv run idx manifest
uv run pytest
```

`idx build` тегли и парсва посочените източници, после слива всички `shards/shard-*.sqlite` в `index.sqlite`. `idx combine` само слива.

## За консуматора (enrichment)

```sh
uv add "terminology-indexes @ git+https://github.com/maturabg/terminology-indexes@lib-v0.1.0"
```

```python
from terminology_indexes import LinkRecord, download_release, load_providers

index = download_release("dl")                 # latest release; token=... ако repo-то е частно
with load_providers(index) as registry:        # IndexVersionError при друг schema_version
    hits = registry.search_all("decorator", lang="en", sources=None, limit=10, per_source=3)
    result = registry.check(LinkRecord(hits[0].source, hits[0].external_id, hits[0].url))
```

`search_all` и `check` не казват дали отговорът е от индекса или от API. Договорът е в `contract.py`; библиотеката се версионира с tag `lib-vX.Y.Z`, данните — с release `index-YYYYMMDD`.

## Структура

- `sources/<id>.yaml` — регистърът; `status: active` изисква адаптер в `ingest/__init__.py`.
- `src/terminology_indexes/normalize.py` — `normalize_term()` (`label_norm`) и `term_key()` (`label_key`); всяка промяна вдига `NORM_VERSION`.
- `src/terminology_indexes/schema.sql` — схемата; `SCHEMA_VERSION` е в `model.py`.
- `src/terminology_indexes/contract.py` — `Provider`, `Candidate`, `LinkRecord`, `CheckResult`.
- `src/terminology_indexes/providers/` — `load_providers()`, `Registry.search_all()` / `check()`, `IndexProvider`; live provider-ите се записват в `LIVE_PROVIDERS`.
- `src/terminology_indexes/release.py` — `download_release()`: сваля и проверява `index.sqlite` от release.
- `src/terminology_indexes/ingest/` — по един модул на източник: `fetch()` (мрежа) и `parse()` (само локално, тества се с fixture от `tests/fixtures/`).
- `.github/workflows/release.yml` — ръчен `workflow_dispatch`, публикува release `index-YYYYMMDD`.

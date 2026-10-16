# terminology-indexes

Буферен индекс (`index.sqlite`, SQLite + FTS5) и адаптери на източниците за en2bg техническия речник. План: `TODO.md`, решения: `docs/decisions.md`.

## Локално

```sh
uv sync
uv run idx build --source python_glossary   # raw/ → shards/shard-<id>.sqlite → index.sqlite
uv run idx query "decorator"                # exact label_key, после FTS
uv run idx manifest
uv run pytest
```

`idx build` тегли и парсва посочените източници, после слива всички `shards/shard-*.sqlite` в `index.sqlite`. `idx combine` само слива.

## Структура

- `sources/<id>.yaml` — регистърът; `status: active` изисква адаптер в `ingest/__init__.py`.
- `src/terminology_indexes/normalize.py` — `normalize_term()` (`label_norm`) и `term_key()` (`label_key`); всяка промяна вдига `NORM_VERSION`.
- `src/terminology_indexes/schema.sql` — схемата; `SCHEMA_VERSION` е в `model.py`.
- `src/terminology_indexes/ingest/` — по един модул на източник: `fetch()` (мрежа) и `parse()` (само локално, тества се с fixture от `tests/fixtures/`).
- `.github/workflows/release.yml` — ръчен `workflow_dispatch`, публикува release `index-YYYYMMDD`.

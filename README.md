# terminology-indexes

Буферен индекс (`index.sqlite`, SQLite + FTS5) и адаптери на източниците за en2bg техническия речник. План: `TODO.md`, решения: `docs/decisions.md`.

## Локално

```sh
uv sync
uv run idx build --source python_glossary --source mitre_cwe   # raw/ → shards/shard-<id>.sqlite → index.sqlite
uv run idx query "decorator"                # search_all: exact > alias > FTS, лимит по източник
uv run idx check python_glossary decorator https://docs.python.org/3/glossary.html#term-decorator
uv run idx fetch --dest dl                  # последният release → dl/index.sqlite (проверен SHA-256)
uv run idx manifest
uv run pytest
```

`idx build` тегли и парсва посочените източници, после слива всички `shards/shard-*.sqlite` в `index.sqlite`. `idx combine` само слива.

Активни източници: `python_glossary`, `nist_csrc`, `mitre_cwe`, `ecma262`, `webref`, `git_glossary`, `postgresql_glossary`, `unicode_glossary`, `google_ml`, `mdn`, `cncf_glossary`, `owasp_cheatsheets`, `owasp_genai`, `rfc_editor`, `nist_dads`. Webref, MDN, CNCF и OWASP Cheat Sheets се теглят с `git` (shallow sparse clone).

## Нощен refresh

`.github/workflows/refresh.yml` тръгва всеки ден в 20:47 UTC (и ръчно, с `sources` и `force`). Стъпките са CLI команди, затова се пускат и локално:

```sh
uv run idx plan                                  # JSON списък на дължимите (refresh от yaml-а спрямо checked_at)
uv run idx shard nist_csrc                       # shards/shard-<id>.sqlite + status-<id>.json; грешка = status failed, exit 0
uv run idx assemble --due '["nist_csrc"]' --previous-dir previous --release-tag index-test --summary summary.md
```

- `assemble` избира по един shard на източник: новия, ако е минал guards (`max_row_drop`, `golden` заявките от yaml-а), иначе този от предишния release.
- Ако нищо не е построено наново, release не излиза; `manifest/sources.json` пак се commit-ва с новото `checked_at` (това е и keepalive-ът).
- `outcome` на източник: `built`, `unchanged` (същият SHA-256 на суровите данни), `not_due`, `failed`, `rejected`. При `failed` / `rejected` се отваря issue с label `source:<id>`; затваря се, когато източникът се оправи.
- Release `index-YYYYMMDD` (втори run в същия ден: `index-YYYYMMDD.2`), пазят се последните 14. В него: `index.sqlite.zst`, `shard-*.sqlite.zst`, `manifest.json` и `NOTICE.md` (атрибуция и лиценз на всеки източник; `idx assemble --notice`).

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
- `src/terminology_indexes/ingest/` — по един модул на източник: `fetch()` (мрежа) и `parse()` (само локално, тества се с fixture от `tests/fixtures/`). Общи: `html_page.py` (една HTML страница: robots.txt, теглене, хеш на извлечените записи), `git_sparse.py` (shallow sparse clone, хеш на прочетените файлове), `markdown.py` (frontmatter, заглавия и абзаци извън code fences) и `text.py` (етикети от заглавие, dedupe по `label_key`).
- `src/terminology_indexes/refresh.py` — `plan`, `refresh_source`, `assemble`: стъпките на нощния refresh.
- `manifest/sources.json` — последният manifest; пише го само `refresh.yml`.
- `.github/workflows/refresh.yml` — нощен cron + `workflow_dispatch`: plan → fetch (matrix) → combine → publish → commit → issues.

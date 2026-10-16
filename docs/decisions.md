# Решения

- хранилището е публично. Може да стане частно завбъдеще, с цел добавяне на нови източници с лицензи, ограничаващи преразпространение;
- install name `terminology-indexes`, import `terminology_indexes`;
- Python 3.14, `uv`, build backend `uv_build`, src layout (`src/terminology_indexes/`);
- версията в `pyproject.toml` е `0.0.0` до tag `lib-v0.1.0` в итерация 2;
- data releases: `index-YYYYMMDD`, library tags: `lib-vX.Y.Z`.

**Регистър на източниците**

- `sources/<id>.yaml` е единственият източник на истина за график, лиценз и статус. Има 28 записа за 27 сайта: OWASP е разделен на `owasp_cheatsheets` и `owasp_genai`. Разпределението е 21 индексни (от тях Wiktionary е индекс + live check), 4 live и 3 gated.

| Поле / стойност | Защо |
| --- | --- |
| `site_no` | връзка с номерацията в `sites_licenses.md` (`"17a"`, `"17b"`) |
| `iteration` | в коя итерация влиза; `plan` job-ът ще може да филтрира по нея |
| `live: { api, auth, secret }` | за live и gated източниците: endpoint, `none` / `key` / `credentials` и името на env променливата. Live provider без своя secret не се регистрира |
| `fetch: null`, `refresh: null` | за live и gated: нищо не се тегли по график |
| `fetch.method`: `http_file`, `html_index`, `wp_rest` | `objects.inv` и `rfc-index.xml` не са ZIP; NIST DADS и Старобългарският са crawl на азбучни индекси; OWASP GenAI е WordPress REST |
| `license.class: copyleft` | GPL (Git Glossary) не е нито `cc_by_sa`, нито `open` |
| `stable_id` | имената са описателни (`std_term`, `cwe_id`, `qid`, …) и не са enum |

- всички индексни и live са `planned`, защото още няма код;
- Cambridge, ISO OBP и IEC са `gated` + `blocked`;
- Старобългарският речник е `index` + `blocked`, докато няма отговор на писмото;
- Etymonline е `planned`: влиза само като каталог „лема → URL“ от sitemap, без съдържание.
- паралелна задача е лицензният клас да се анализира периодично (последно всички лицензи са проверени на 2026-10-14)
    - изключения
        - Wikidata/Wikipedia е `cc_by_sa`, но snippet се взема само от описанието в Wikidata (CC0);
        - NIST CSRC и NIST DADS са `public_domain` с филтър на ниво запис;
        - Encyclopedia of Mathematics е `restricted` (оригиналите © Springer).
- snippet не се показва на сайта, той стига само до LLM-а. Правилото следва колоната „Снипет в публично repo“:
    - ✅ дава `short` (до 200 знака);
    - ❌ и ⚠️ дават `none`;
        - Изключения към `none`, въпреки ✅ или ◐:
            - Git Glossary: GPL текст би изисквал отделен GPL-съвместим файл в release-а;
            - Webref и ECMA-262: данните нямат текст на дефиниция;
            - Wiktionary: в индекса са само заглавия.
    - ◐ дава `short` с филтър на ниво запис, описан в `notes` (NIST CSRC, NIST DADS, RFC, EuroVoc).
- Езици на етикетите - само EN и BG. Колоната `labels.lang` остава за пълнота
- Python: pull pinned `3.14/objects.inv`, URL for display `/3/glossary.html#term-…`;
- PostgreSQL: pull pinned `/docs/18/glossary.html`, URL for display `/docs/current/glossary.html#GLOSSARY-…`.
- В итерация 10 различни LLM модели предлагат линкове за едни и същи речникови записи. Анализират се разногласията между тях и въз основа на анализа се избира финалният модел.


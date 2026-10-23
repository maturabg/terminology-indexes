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

**Нощен refresh**

- `refresh.yml` замества ръчния `release.yml`. Логиката е в Python (`refresh.py`, командите `idx plan|shard|assemble`), YAML-ът само вика CLI и `gh`.
- Паднал източник не чупи run-а: `idx shard` записва `status: failed` и излиза с 0. Видимостта е issue `source:<id>` и job summary, не червен job.
- „Непроменен“ = същият SHA-256 на суровите данни като в manifest-а. За NIST CSRC се хешира JSON-ът, не ZIP-ът — ZIP-ът се преиздава всеки ден.
- Дължимост: `checked_at` (последно успешно теглене, променено или не) + `refresh` минус толеранс `min(12 h, refresh / 2)` за разминаването на cron-а. Паднал източник не мести `checked_at`, така че е дължим пак на следващия ден.
- Нов release само ако поне един shard е построен наново и приет (или `force`); иначе `release_tag` в manifest-а остава стария. Така `snapshot_version` на линковете не се сменя без нужда.
- Guards по shard преди сливането: `max_row_drop` спрямо предишния shard и `golden` заявките от yaml-а. Отхвърлен shard се заменя с предишния. След сливането `golden` се пускат отново върху целия индекс; провал там спира release-а.
- Release-ът съдържа точно shards, влезли в индекса, а `manifest.json` в него е същият като `manifest/sources.json`.
- Втори run в един ден: `index-YYYYMMDD.2`, `.3`, … — съществуващ tag не се презаписва, защото някой може вече да го е пиннал.

- HTML се парсва с `beautifulsoup4` (`html.parser`, чист Python). Преди теглене на HTML страница се чете `robots.txt` (403 на robots.txt = забрана, 404 = без правила).
- „Непроменен“ е хеш на това, което парсерът чете, когато суровите байтове се менят без нова информация:
    - HTML страници: хеш на извлечените записи — devsite (Google ML) връща нов nonce и разбъркан script config при всяка заявка;
    - Webref: `ed/dfns/*.json` + използваните полета от `ed/index.json` (датите на crawl-а са нови всеки ден);
    - CWE: XML-ът в ZIP-а; ECMA-262: `biblio.json` в tarball-а.
- `snapshot_version`: CWE `<версия на каталога>+<hash>`, ECMA-262 `<npm версия>+<hash>`, Webref `<дата на commit>+<commit>`, Git `master+<hash>`, HTML страници само `<hash>` (нямат версия; `fetched_at` е в таблицата `sources`).
- ECMA-262 „пинната версия“: `fetch.version` е dist-tag (`latest`) или точна версия; всяко теглене записва точната версия и сверява tarball-а с `integrity` от npm registry-то. Пакетът излиза при всеки commit в спецификацията, затова фиксирана версия в yaml-а би остаряла.
- Етикети от заглавие (`ingest/text.py`): `X (Y)` дава и `X`; `Y` става етикет само ако е `also Y` или едната страна е съкращение (`AUC (Area under the ROC curve)`, `Input/Output (I/O)`). Квалификатор като `node (decision tree)` не става етикет — иначе „decision tree“ би намирал „node“. Дубликати по `label_key` отпадат, първият (`pref`) остава.
- Стари имена без собствен запис стават `redirect` етикети на целта: `Obsolete for:` в Git Glossary (и самият запис е `status: redirect` + `replaced_by`), `<dt>` без id със „See X“ в PostgreSQL. Така търсенето по старото име намира новия запис като `alias`.
- MITRE CWE: Weakness, Category и View (View е `kind: document`); `external_id` = `CWE-<n>`, който е и alt етикет. `replaced_by` на deprecated запис се взема от текста му само ако сочи точно един активен запис, който не е View (`organizing the Development View (CWE-699)` е контекст, не заместник). `Obsolete` остава `active` — страницата съществува, статусът е в `extra.cwe_status`.
- ECMA-262: само `term` (variants → alt) и `clause` (етикетът е без сигнатурата: `Math.pow ( base, exponent )` → `Math.pow`). Abstract operations, productions, таблици и стъпки са вътрешности на спецификацията. `external_id` на термин е `term:<термин>`, защото много термини делят anchor-а на своя clause.
- Webref: само WHATWG и W3C (Ecma е отделен източник, другите организации имат други лицензи), без `discontinued`; само `access: public`, неинформативни, без `for` (членовете на IDL интерфейси) и от типовете в `ingest/webref.py` (без dictionary, enum, typedef, callback, abstract-op…). Около 8 300 от 55 000 dfns. `external_id` = `<shortname>#<id>`, лицензът е в `extra.license`.
- `NOTICE.md` в release-а: атрибуция, лиценз и snapshot на всеки източник в индекса, плюс полето `notice` от yaml-а (пълният текст за MITRE и Ecma). Пише се от `idx assemble --notice`.
- Fixtures на Unicode и Git Glossary са със същата структура, но с измислен текст — лицензите им не позволяват да разпространяваме дефинициите (Unicode) или изискват отделен GPL файл (Git).

- Git източниците (Webref, MDN, CNCF, OWASP Cheat Sheets) делят `ingest/git_sparse.py`: shallow, blobless, sparse clone на `SPARSE`, `fetch.branch` по желание (Webref: `curated`). Хешът е на файловете, които парсерът чете, не на commit-а — повечето commit-и пипат други части на repo-то. `snapshot_version` = `<дата на commit>+<commit>`; commit-ът се пази в `commit.json` до файловете.
- `title_variants`: `Y` от `X (Y)` е етикет само ако наистина е друго име на `X` — идентификатор (`tf.data`) или акроним, чиито букви подред започват буквите на другата страна (`AUC` / `Area under the ROC curve`, `XHR` / `XMLHttpRequest`). `Node (DOM)`, `Block (CSS)` вече не дават `DOM`, `CSS`. Shards от итерация 4 се обновяват при следваща промяна на суровите данни или с `force`.
- MDN: всички `glossary-definition` и `glossary-disambiguation` страници (disambiguation „Boolean“ е истинска страница, децата ѝ са „Boolean (JavaScript)“ …). `external_id` = `slug`, URL = `/en-US/docs/<slug>`; `short-title` е alt етикет. Snippet = първият абзац; KumaScript макросите се заменят с текста на линка си (`{{Glossary("SPA", "single-page apps")}}` → „single-page apps“), банерите изчезват.
- CNCF: няма bg превод (16 езика към 2026-10-23), `langs: [en]`. Sitemap-ът изостава от repo-то (липсват живи страници като `hypervisor`), затова не е whitelist; публикувано = файл в `content/en/` без `draft: true`.
- OWASP Cheat Sheets: всеки cheat sheet е `document` (етикет без „Cheat Sheet“), всяка `##` секция — `spec_section` с anchor-а на Python-Markdown `toc` (проверено 1:1 срещу живия сайт, вкл. `_1` за повторени id). Не са записи: заглавия в 3+ cheat sheets (Introduction, References — структура, не тема), заглавия над 6 думи (изречения) и секциите на `DEPRECATED:` / `(Historical)` cheat sheets. Номерацията („Section 7:“, „7.“) отпада от етикета. „Please visit [X](X.md)“ → `replaced_by`.
- OWASP GenAI: WordPress REST има собствен тип `glossaries` — всеки термин е със собствена страница, не anchor. Плюс `llmrisk` (текущият OWASP Top 10 for LLM, `kind: concept`, етикети „Prompt Injection“, „LLM01:2025“, „LLM01“). Хешът е на записите, защото `modified` се мени и без промяна в това, което пазим.
- RFC Editor: само `rfc-entry` (без BCP/STD/FYI записи и неиздадени номера); `is-also` дава alt етикети („BCP 14“, „STD 97“), половините на „X -- Y“ — също. Ключовите думи не са етикети: „HTTP“ е ключова дума на стотици RFC. URL е `/info/rfcNNNN/` (без наклонената черта има 301). `obsoleted-by` → `deprecated`; `replaced_by` само при един наследник, както при CWE — RFC 2616 (шест наследника) при `check` е `dead`, списъкът е в `extra.obsoleted_by`.
- NIST DADS: целият азбучен индекс е една страница — 1 100+ термина и „X: see Y“ (→ `redirect` етикет). Дефинициите не се теглят: при учтивите 0,2 rps това е над час на refresh. Затова записите са без snippet.
- Fixtures на MDN, CNCF, OWASP и GenAI са със същата структура, но с измислен текст (CC BY-SA / CC BY текст в repo-то би изисквал атрибуция и share-alike на файла). RFC и DADS са реални откъси (TLP / public domain).

- IATE: анонимно е достъпен само пълният TBX export от 2019-02-26 (`/em-api/artifacts/full-tbx` пренасочва към S3 `IATE_download.zip`: 113 MB ZIP, 1,9 GB TBX). Актуалният export е async job (`/em-api/ws/async-jobs`, type 18) само за влезли потребители с EU Login. Дотогава индексът е от 2019: ~653 000 записа (EN 616 000, EN+BG 35 000, само BG 1 900); shard 228 MB, 51 MB със zstd; parse 60 s, 41 MB RAM (поточен `iterparse`, `body.clear()` след всеки запис).
    - Запис влиза, ако има EN или BG термин с reliability ≥ 2 и тип `fullForm`, `abbreviation` или `shortForm` (без `phraseologicalUnit` и `formula`). `deprecated` / `superseded` термини стават `redirect` етикети. Заглавие: preferred, после full form, после съкращение; при равенство — по reliability.
    - `external_id` = числото от `IATE-<n>`, URL `https://iate.europa.eu/entry/result/<n>`; домейните (`subjectField`, „3226, 3236“) → `extra.domain`. Export-ът няма дефиниции, затова `snippet_policy: none`. `lang` на запис с EN и BG е `mul`.
    - Филтър по домейни не е нужен — размерът е далеч под 1,5 GB.
- EuroVoc: `fetch.method: cellar_sparql`. Страницата за сваляне е JS; Cellar SPARQL намира последния release на `dataset/eurovoc` (по `work_date_document`) и неговата manifestation `SKOS_CORE`, файлът е `<manifestation>/DOC_1` (ZIP с един RDF/XML, 60 MB). `snapshot_version` = `<версия>+<hash на RDF-а>` (4.24 към 2026-10-23). Само концепти от тезауруса (`inScheme` 100141): домейните („12 LAW“) са концепти от друга схема, микротезаурусите са схеми. 7 515 концепта, 7 478 с BG етикет.
    - `external_id` = URI на концепта (той е и аргументът на SPARQL `ASK` в итерация 7). URI-то връща 403 извън браузър, затова URL е страницата в EU Vocabularies (`…/concept/-/resource?uri=<URI>`). Snippet = EN `skos:definition` (1 555 концепта).
    - Release-ът в Cellar няма собствен лиценз: важи общото уведомление на Publications Office (повторна употреба с атрибуция) — `cc_by` остава.
- Wiktionary: dump-ът `all-titles-in-ns0` е безполезен за индекса — 9,2 млн. заглавия в enwiktionary (всички езици и словоформи; само ASCII са 5,5 млн.) и 790 000 в bgwiktionary (почти всички — словоформи). Вместо него: членовете на `Category:English lemmas` (~885 000) и `Категория:Думи в българския език` (~22 000) през `list=categorymembers`. `fetch.method: mediawiki_category`, `rate_limit.rps: 2` (последователни заявки, ~1 800 общо).
    - Първо теглене (2026-10-23): 884 430 EN + 22 149 BG леми, 18 мин, 210 MB RAM; shard 252 MB, 53 MB със zstd. Трите нови източника заедно: 1,57 млн. записа, 486 MB индекс.
    - `external_id` = `<lang>:<заглавие>`, `pageid` е в `extra` (за live `check` в итерация 7). EN URL-ът сочи секцията: `…/wiki/<заглавие>#English`.
    - robots.txt на Wikimedia забранява `/w/` за crawler-и; API Etiquette изрично позволява последователни заявки с User-Agent, затова за MediaWiki API robots.txt не се чете (за EoM — също).
- Encyclopedia of Mathematics: `status: paused`. Целият сайт (и `api.php`, и `/wiki/`) връща 502 на 2026-10-16 и 2026-10-23. Адаптерът е готов (`list=allpages`, без redirects, `external_id` = `pageid`) и е тестван с fixture; при възстановяване — `active` и `golden`.
- `ingest/mediawiki.py` е общ за Wiktionary и EoM: страниране по `continue`, `rps` от регистъра, retry при 429 / 5xx / мрежова грешка. Страниците се пишат като сортиран `.jsonl`, хешът е на тях.
- Двуезичен бонус: `search_all(query, translation=...)` търси и превода (`translation_lang="bg"`) в същия provider. Запис, намерен и от двете страни, се вдига с един тип съвпадение (alias застава до exact, FTS — до alias) и при равенство е пред останалите; `Candidate.also_matched` носи BG етикета. Всяка страна гледа до 20 кандидата на източник (`BILINGUAL_POOL`). Пример: `firewall` + „защитна стена“ → IATE 176235 „Internet firewall“ излиза пред трите „firewall“ / „fire wall“ без BG.
- `Candidate.also_matched` и `search_all(translation=…)` са нови, със стойности по подразбиране — стар код работи без промяна. Версия на библиотеката: 0.2.0 (tag `lib-v0.2.0` след push).
- Fixtures на IATE и EuroVoc са реални записи (свободна повторна употреба с атрибуция); Wiktionary и EoM — само заглавия.

- Live provider-ите живеят в библиотеката (`providers/`), а заявките тръгват от enrichment. Нито един от четирите не иска ключ, затова всички се регистрират без secret; `secret_env` остава за EUR-Lex SOAP и Cambridge. Пакетът не носи `sources/*.yaml`, затова `api`, `rps` и `daily` са константи в класа, а тест ги сверява с yaml-а.
- `load_providers(..., live=False)` дава само индекса: golden заявките в refresh и тестовете не излизат в мрежата; `idx query|check --no-live` — същото от CLI.
- `search_all` пита live provider-ите паралелно (нишка на provider, всеки със своя rate limit и lock), индексните остават в главната нишка, защото делят една SQLite връзка. Редът при равенство е по provider, не по това кой отговори пръв.
- `check` на live: `HTTPError` → общите правила (404/410 `dead`, 301/308 `moved`, 403/429/5xx `unknown`); мрежова грешка, timeout и дневен лимит → `unknown`.
- Wikidata: `wbsearchentities` на езика на заявката + `wbgetentities` (етикети, описания, sitelinks на enwiki/bgwiki). Само записи със статия в EN или BG Уикипедия (линкът е към статия); пояснителните страници отпадат по описание. `exact` / `alias` по `label_key` и типа на съвпадението, иначе `fts`. Слят QID със същата статия е `ok` с reason — линкът е валиден; друга статия е `moved`.
- Wiktionary: `WiktionaryProvider` е `IndexProvider` с live `check`: `action=parse&prop=tocdata&redirects=1` по `pageid` от `extra` (по заглавие, ако записът е излязъл от индекса). Няма страница = `dead`, няма секция English / Български = `dead`, друго заглавие = `moved`.
- W3C API няма търсене: първото `search` чете целия списък (~1 700, две заявки по 1 000) и търси локално. Етикети: заглавието, shortname, заглавието без „Module Level N“ / версия, без скобите и самото съкращение в скоби (`WCAG`). Детайлите на всеки кандидат дават описанието (snippet) и статуса; Retired не се предлагат, но при `check` са `ok` с reason. Преименуван shortname (`css3-grid-layout` → `css-grid-1`) API-то пренасочва — `moved`.
- EUR-Lex: Cellar SPARQL `bif:contains` по фраза от думите на заявката (кавички и оператори не стигат до заявката). Само сектор 3 и типове R, L, D без поправки (`…R(02)`), до 100 реда, класирани локално: краткото име в скоби = заявката (`exact`), в сила, на Парламента и Съвета, по-кратко заглавие. `check` е HEAD към `publications.europa.eu/resource/celex/<CELEX>`: 303 = `ok`, 404 = `dead`. Самият eur-lex.europa.eu връща 202 (bot challenge) на скриптове, затова не се проверява.
- ЛЕКСИТ: GET на `/dictionary_portal/lang/bg/<дума>` (формата е POST, но GET и пътят дават същата страница). Резултат = заглавие „Основна форма“ или блок „Резултати от: <речник>“; речниците влизат в заглавието на кандидата, текст — не. Форма на дума („компютъра“) дава основната форма като `alias` и линк към нейната страница. Заявки само на кирилица — при 0,2 rps и 500 на ден латиница е загуба.
- Etymonline: `robots.txt` позволява `/word/` и сам обявява sitemap-а; `/sitemap.xml` пренасочва към `/sitemaps/words-en.xml` (47 294 леми, 5 MB, shard 10 MB). Само лема → URL, `snippet_policy: none`; хешът е на лемите, защото `lastmod` се мени. Страниците `/word/` и условията връщат 403 на скриптове (Cloudflare) — не се теглят.
- Старобългарският речник остава `blocked`: писмото не е изпратено (итерация 9).
- Версия на библиотеката: 0.3.0 (tag `lib-v0.3.0` след push): нови provider-и и `load_providers(live=...)`; стар код работи без промяна, но `search_all` вече пита и live API-тата.

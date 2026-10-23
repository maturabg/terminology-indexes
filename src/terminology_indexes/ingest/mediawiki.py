"""MediaWiki Action API lists (``list=categorymembers``, ``list=allpages``) and page URLs.

The pages are written to ``<wiki>.jsonl`` (``{"pageid", "title"}`` per line, sorted
by title), so ``parse`` reads files and the hash is of the titles, not of the API's
paging.
"""

import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterable, Iterator
from pathlib import Path

from terminology_indexes.ingest.base import TIMEOUT, RawSnapshot, make_request

MAX_LIMIT = 500  # per request, for clients without the apihighlimits right
RETRIES = 4


def get_json(url: str) -> dict:
    """GET with retries on 429 / 5xx / network errors (Wikimedia hiccups now and then)."""
    for attempt in range(RETRIES + 1):
        try:
            with urllib.request.urlopen(make_request(url), timeout=TIMEOUT) as r:
                data = json.load(r)
            if "error" in data:
                raise RuntimeError(f"{url}: {data['error']}")
            return data
        except urllib.error.HTTPError as e:
            if attempt == RETRIES or not (e.code == 429 or e.code >= 500):
                raise
        except urllib.error.URLError, TimeoutError:
            if attempt == RETRIES:
                raise
        time.sleep(5 * 2**attempt)
    raise AssertionError("unreachable")


def list_pages(api: str, params: dict[str, str], *, rps: float) -> Iterator[dict]:
    """Every item of one ``list=`` query, following ``continue``; at most ``rps`` requests a second."""
    key = params["list"]
    base = {"action": "query", "format": "json", "formatversion": "2", **params}
    cont: dict[str, str] = {}
    while True:
        started = time.monotonic()
        data = get_json(f"{api}?{urllib.parse.urlencode(base | cont)}")
        yield from data["query"][key]
        if "continue" not in data:
            return
        cont = data["continue"]
        time.sleep(max(0.0, 1 / rps - (time.monotonic() - started)))


def write_pages(path: Path, pages: Iterable[dict]) -> int:
    rows = sorted({(p["title"], p["pageid"]) for p in pages if p.get("ns", 0) == 0})
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as out:
        for title, pageid in rows:
            out.write(json.dumps({"pageid": pageid, "title": title}, ensure_ascii=False) + "\n")
    return len(rows)


def read_pages(path: Path) -> Iterator[dict]:
    with path.open(encoding="utf-8") as f:
        for line in f:
            yield json.loads(line)


def pages_snapshot(paths: Iterable[Path], root: Path) -> RawSnapshot:
    """Hash of the page files; no API has a version, so ``snapshot_version`` is the hash."""
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(path.name.encode() + b"\0")
        with path.open("rb") as f:
            digest.update(hashlib.file_digest(f, "sha256").digest())
    sha = digest.hexdigest()
    return RawSnapshot(path=root, sha256=sha, snapshot_version=sha[:12])


def page_url(base: str, title: str) -> str:
    """``base`` + the title the way MediaWiki links it (``hash table`` -> ``hash_table``)."""
    return base + urllib.parse.quote(title.replace(" ", "_"), safe="/:@!$*(),;~'")

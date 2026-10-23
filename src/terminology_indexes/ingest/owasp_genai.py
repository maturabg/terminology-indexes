"""OWASP GenAI Security Project through the WordPress REST API.

Two post types, both with a page of their own: ``glossaries`` (the glossary
terms) and ``llmrisk`` (the current OWASP Top 10 for LLM Applications).
"""

import hashlib
import html
import json
import re
import time
import urllib.request
from collections.abc import Iterator
from dataclasses import asdict
from pathlib import Path

from terminology_indexes.ingest.base import TIMEOUT, Adapter, RawSnapshot, make_request
from terminology_indexes.ingest.html_page import RobotsDenied, robots_allowed
from terminology_indexes.ingest.text import dedupe, heading_labels, squash
from terminology_indexes.model import Entry, Label

FIELDS = "id,slug,link,title,excerpt,modified"
PER_PAGE = 100
# post type -> entry kind
TYPES = {"glossaries": "term", "llmrisk": "concept"}

_TAG = re.compile(r"</?[a-zA-Z][^<>]*>")
# "LLM01:2025 Prompt Injection"
_RISK = re.compile(r"(LLM\d+):(\d{4})\s+(.+)")


def text(rendered: str) -> str:
    return squash(html.unescape(_TAG.sub(" ", rendered)))


def excerpt(rendered: str, title: str) -> str | None:
    """The excerpt starts with the term itself ("Embeddings Embeddings are ..."); drop it."""
    out = text(rendered)
    if out.casefold().startswith(title.casefold()):
        out = out[len(title) :].lstrip(" :–-")
    return out.removesuffix("[…]").strip() or None


class OwaspGenai(Adapter):
    def fetch(self, raw_dir: Path) -> RawSnapshot:
        api = self.source.fetch["url"]
        if not robots_allowed(api):
            raise RobotsDenied(f"{api} is disallowed by robots.txt")
        delay = 1 / (self.source.raw.get("rate_limit") or {}).get("rps", 1)
        root = raw_dir / self.source.id
        root.mkdir(parents=True, exist_ok=True)
        for post_type in TYPES:
            items, page, pages = [], 1, 1
            while page <= pages:
                url = f"{api}{post_type}?per_page={PER_PAGE}&page={page}&_fields={FIELDS}"
                with urllib.request.urlopen(make_request(url), timeout=TIMEOUT) as r:
                    pages = int(r.headers.get("X-WP-TotalPages") or 1)
                    items += json.load(r)
                page += 1
                time.sleep(delay)
            (root / f"{post_type}.json").write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
        return self.snapshot(root)

    def snapshot(self, root: Path) -> RawSnapshot:
        # Hash the entries: "modified" moves on edits that change nothing we keep.
        entries = [asdict(e) for e in self.parse(RawSnapshot(path=root, sha256="", snapshot_version=""))]
        sha = hashlib.sha256(json.dumps(entries, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        modified = max(
            (i["modified"][:10] for t in TYPES for i in json.loads((root / f"{t}.json").read_text(encoding="utf-8"))),
            default="",
        )
        return RawSnapshot(path=root, sha256=sha, snapshot_version=f"{modified}+{sha[:12]}")

    def parse(self, snapshot: RawSnapshot) -> Iterator[Entry]:
        for post_type, kind in TYPES.items():
            items = json.loads((snapshot.path / f"{post_type}.json").read_text(encoding="utf-8"))
            for item in sorted(items, key=lambda i: i["id"]):
                title = text(item["title"]["rendered"])
                labels = heading_labels(title)
                extra = {"type": post_type}
                if m := _RISK.fullmatch(title):
                    # "Prompt Injection" first, then "LLM01:2025" and "LLM01"
                    labels = dedupe([Label(m[3], "en", "pref"), Label(f"{m[1]}:{m[2]}", "en", "alt"), *labels[1:]])
                    labels = dedupe([*labels, Label(m[1], "en", "alt")])
                    extra |= {"risk_id": m[1], "edition": m[2]}
                yield Entry(
                    external_id=f"{post_type}/{item['slug']}",
                    url=item["link"],
                    title=title,
                    kind=kind,
                    lang="en",
                    snippet=excerpt(item["excerpt"]["rendered"], title),
                    extra=extra,
                    labels=labels,
                )

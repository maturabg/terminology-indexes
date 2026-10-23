"""Base for sources that are one HTML page (``fetch.method: html_page``)."""

import hashlib
import json
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from dataclasses import asdict
from pathlib import Path

from bs4 import BeautifulSoup, Tag

from terminology_indexes.ingest.base import TIMEOUT, USER_AGENT, Adapter, RawSnapshot, download, make_request


def attr(tag: Tag, name: str) -> str:
    """An attribute as one string (bs4 types multi-valued ones like ``class`` as lists)."""
    value = tag.get(name)
    return value if isinstance(value, str) else " ".join(value or [])


class RobotsDenied(RuntimeError):
    pass


def robots_allowed(url: str) -> bool:
    """``robots.txt`` of the host allows our User-Agent to fetch ``url``; no robots.txt allows all."""
    parts = urllib.parse.urlsplit(url)
    robots = urllib.robotparser.RobotFileParser()
    try:
        with urllib.request.urlopen(make_request(f"{parts.scheme}://{parts.netloc}/robots.txt"), timeout=TIMEOUT) as r:
            robots.parse(r.read().decode("utf-8", "replace").splitlines())
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return False
        return True  # 404 and friends: no rules
    return robots.can_fetch(USER_AGENT, url)


class HtmlPage(Adapter):
    """``fetch`` downloads ``fetch.url`` once; subclasses parse ``soup(snapshot)``."""

    def fetch(self, raw_dir: Path) -> RawSnapshot:
        url = self.source.fetch["url"]
        if not robots_allowed(url):
            raise RobotsDenied(f"{url} is disallowed by robots.txt")
        path = raw_dir / self.source.id / "page.html"
        download(url, path, headers={"Accept": "text/html"})
        return self.snapshot(path)

    def snapshot(self, path: Path) -> RawSnapshot:
        # Hash what the parser extracts, not the bytes: devsite pages carry a fresh nonce
        # and reshuffled script config on every request. A page has no version of its own.
        entries = [asdict(e) for e in self.parse(RawSnapshot(path=path, sha256="", snapshot_version=""))]
        sha = hashlib.sha256(json.dumps(entries, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        return RawSnapshot(path=path, sha256=sha, snapshot_version=sha[:12])

    @staticmethod
    def soup(snapshot: RawSnapshot) -> BeautifulSoup:
        return BeautifulSoup(snapshot.path.read_bytes(), "html.parser")

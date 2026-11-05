"""Adapter contract: ``fetch`` downloads raw data, ``parse`` turns it into entries."""

import hashlib
import http.client
import json
import logging
import ssl
import time
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from terminology_indexes import __version__
from terminology_indexes.model import Entry, Source

USER_AGENT = f"terminology-indexes/{__version__} (+https://github.com/maturabg/terminology-indexes)"
TIMEOUT = 60
RETRIES = 4

log = logging.getLogger(__name__)


class TemporaryError(Exception):
    """A failure that may go away by itself, for what has no exception type of its own (``git`` exit codes)."""


TEMPORARY = (
    urllib.error.URLError,
    TimeoutError,
    ConnectionError,
    ssl.SSLError,
    http.client.HTTPException,
    TemporaryError,
)


def is_temporary(error: Exception) -> bool:
    """The site or the network is having a bad moment; anything else needs a person (403, 404, parse errors...)."""
    if isinstance(error, urllib.error.HTTPError):
        return error.code == 429 or error.code >= 500
    return isinstance(error, TEMPORARY)


def retrying[T](call: Callable[[], T]) -> T:
    """``call()``, again after 5, 10, 20 and 40 s if it fails with a temporary error."""
    for attempt in range(RETRIES):
        try:
            return call()
        except Exception as e:
            if not is_temporary(e):
                raise
            log.warning("attempt %d failed: %s", attempt + 1, e)
            time.sleep(5 * 2**attempt)
    return call()


@dataclass(frozen=True)
class RawSnapshot:
    path: Path
    sha256: str
    snapshot_version: str


class Adapter(ABC):
    def __init__(self, source: Source) -> None:
        self.source = source

    @abstractmethod
    def fetch(self, raw_dir: Path) -> RawSnapshot:
        """Download the raw data into ``raw_dir``."""

    @abstractmethod
    def parse(self, snapshot: RawSnapshot) -> Iterator[Entry]:
        """Yield entries from a snapshot; must not touch the network."""


def make_request(url: str, headers: dict[str, str] | None = None, token: str | None = None) -> urllib.request.Request:
    """A request with our User-Agent; ``token`` is not forwarded on redirects (e.g. to S3)."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    if token:
        req.add_unredirected_header("Authorization", f"Bearer {token}")
    return req


def request_json(url: str) -> tuple[Any, http.client.HTTPMessage]:
    """GET ``url`` with retries; the parsed body and the response headers."""

    def get() -> tuple[Any, http.client.HTTPMessage]:
        with urllib.request.urlopen(make_request(url), timeout=TIMEOUT) as response:
            return json.load(response), response.headers

    return retrying(get)


def download(url: str, dest: Path, headers: dict[str, str] | None = None, token: str | None = None) -> str:
    """Stream ``url`` into ``dest`` with retries and return its SHA-256."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    request = make_request(url, headers, token)
    tmp = dest.with_name(dest.name + ".part")

    def stream() -> str:
        digest = hashlib.sha256()
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response, tmp.open("wb") as out:
            while chunk := response.read(1 << 16):
                digest.update(chunk)
                out.write(chunk)
        return digest.hexdigest()

    sha = retrying(stream)
    tmp.replace(dest)
    return sha


def sha256_file(path: Path) -> str:
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()

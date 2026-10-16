"""Adapter contract: ``fetch`` downloads raw data, ``parse`` turns it into entries."""

import hashlib
import urllib.request
from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from terminology_indexes import __version__
from terminology_indexes.model import Entry, Source

USER_AGENT = f"terminology-indexes/{__version__} (+https://github.com/maturabg/terminology-indexes)"
TIMEOUT = 60


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


def download(url: str, dest: Path) -> str:
    """Stream ``url`` into ``dest`` and return its SHA-256."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    tmp = dest.with_name(dest.name + ".part")
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response, tmp.open("wb") as out:
        while chunk := response.read(1 << 16):
            digest.update(chunk)
            out.write(chunk)
    tmp.replace(dest)
    return digest.hexdigest()


def sha256_file(path: Path) -> str:
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()

"""NIST CSRC Glossary from the daily ``glossary-export.zip`` (one JSON file)."""

import hashlib
import html
import json
import re
import zipfile
from collections.abc import Iterator
from datetime import date
from pathlib import Path

from terminology_indexes.ingest.base import Adapter, RawSnapshot, download
from terminology_indexes.model import Entry, Label
from terminology_indexes.normalize import term_key

TERM_URL = "https://csrc.nist.gov/glossary/term/"

# Only definitions taken from a NIST publication are US public domain; CNSSI and
# others are cited, not owned (see the yaml notes).
_NIST_SOURCE = re.compile(r"(NIST|NISTIR|FIPS)\b")
_TAG = re.compile(r"</?[a-zA-Z][^<>]*>")
_SPACES = re.compile(r"\s+")


def clean(text: str) -> str:
    """Terms and definitions carry inline HTML (``<em>``, ``<sub>``, ``&nbsp;``, ``&amp;``)."""
    return _SPACES.sub(" ", html.unescape(_TAG.sub("", text))).strip()


def read_export(path: Path) -> tuple[date, bytes]:
    """Return ``(export date, JSON bytes)`` of the single file in the ZIP."""
    with zipfile.ZipFile(path) as z:
        names = [n for n in z.namelist() if n.endswith(".json")]
        if len(names) != 1:
            raise ValueError(f"{path}: expected one JSON file, found {names}")
        info = z.getinfo(names[0])
        return date(*info.date_time[:3]), z.read(info)


def nist_snippet(definitions: list[dict] | None) -> str | None:
    for d in definitions or []:
        if d.get("text") and any(_NIST_SOURCE.match(s.get("text") or "") for s in d.get("sources") or []):
            return clean(d["text"])
    return None


class NistCsrc(Adapter):
    def fetch(self, raw_dir: Path) -> RawSnapshot:
        path = raw_dir / self.source.id / "glossary-export.zip"
        download(self.source.fetch["url"], path)
        return self.snapshot(path)

    def snapshot(self, path: Path) -> RawSnapshot:
        # Hash the JSON, not the ZIP: the ZIP is rebuilt daily even when nothing changed.
        day, data = read_export(path)
        sha = hashlib.sha256(data).hexdigest()
        return RawSnapshot(path=path, sha256=sha, snapshot_version=f"{day.isoformat()}+{sha[:12]}")

    def parse(self, snapshot: RawSnapshot) -> Iterator[Entry]:
        _, data = read_export(snapshot.path)
        for item in json.loads(data.decode("utf-8-sig"))["parentTerms"]:
            url = item["link"]
            if not url.startswith(TERM_URL):
                raise ValueError(f"unexpected term link {url!r}")
            title = clean(item["term"])
            labels, keys = [Label(title, "en", "pref")], {term_key(title)}
            # abbrSyn links an abbreviation and its expansion both ways: either one finds the entry.
            for syn in item.get("abbrSyn") or []:
                alt = clean(syn.get("text") or "")
                if alt and (key := term_key(alt)) not in keys:
                    keys.add(key)
                    labels.append(Label(alt, "en", "alt"))
            yield Entry(
                external_id=url.removeprefix(TERM_URL),
                url=url,
                title=title,
                kind=self.source.kind_default,
                lang="en",
                snippet=nist_snippet(item.get("definitions")),
                labels=labels,
            )

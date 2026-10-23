"""MITRE CWE from ``cwec_latest.xml.zip``: weaknesses, categories and views."""

import hashlib
import re
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Iterator
from pathlib import Path

from terminology_indexes.ingest.base import Adapter, RawSnapshot, download
from terminology_indexes.ingest.text import dedupe, squash
from terminology_indexes.model import Entry, Label

NS = "{http://cwe.mitre.org/cwe-7}"
URL = "https://cwe.mitre.org/data/definitions/{}.html"
# element -> (kind, element with the short text)
ELEMENTS = {
    "Weakness": ("concept", "Description"),
    "Category": ("concept", "Summary"),
    "View": ("document", "Objective"),
}

_CWE_REF = re.compile(r"\bCWE-(\d+)\b")
_VERSION = re.compile(rb"<Weakness_Catalog\b[^>]*\bVersion=\"([^\"]+)\"")


def read_catalog(path: Path) -> bytes:
    with zipfile.ZipFile(path) as z:
        names = [n for n in z.namelist() if n.endswith(".xml")]
        if len(names) != 1:
            raise ValueError(f"{path}: expected one XML file, found {names}")
        return z.read(names[0])


def replacement(text: str, ids: dict[str, str], views: set[str]) -> str | None:
    """The one active entry a deprecation text points to ("duplicate of CWE-908", "See CWE-532").

    Views are mentioned as context ("organizing the Development View (CWE-699)"), not as targets.
    Several candidates mean the content was split: no single replacement.
    """
    targets = {n for n in _CWE_REF.findall(text) if n not in views and ids.get(n) == "active"}
    return f"CWE-{targets.pop()}" if len(targets) == 1 else None


class MitreCwe(Adapter):
    def fetch(self, raw_dir: Path) -> RawSnapshot:
        path = raw_dir / self.source.id / "cwec_latest.xml.zip"
        download(self.source.fetch["url"], path)
        return self.snapshot(path)

    def snapshot(self, path: Path) -> RawSnapshot:
        # Hash the XML, not the ZIP, like NIST CSRC: a re-zipped file is not new data.
        data = read_catalog(path)
        sha = hashlib.sha256(data).hexdigest()
        if not (m := _VERSION.search(data, 0, 4096)):
            raise ValueError(f"{path}: no Weakness_Catalog Version")
        return RawSnapshot(path=path, sha256=sha, snapshot_version=f"{m[1].decode()}+{sha[:12]}")

    def parse(self, snapshot: RawSnapshot) -> Iterator[Entry]:
        root = ET.fromstring(read_catalog(snapshot.path))
        items = [(tag, el) for tag in ELEMENTS for el in root.iter(NS + tag)]
        status = {el.get("ID", ""): "deprecated" if el.get("Status") == "Deprecated" else "active" for _, el in items}
        views = {el.get("ID", "") for tag, el in items if tag == "View"}
        for tag, el in items:
            cwe_id, name = el.get("ID", ""), squash(el.get("Name", ""))
            kind, text_tag = ELEMENTS[tag]
            short = el.find(NS + text_tag)
            text = squash("".join(short.itertext())) if short is not None else ""
            labels = [Label(name.removeprefix("DEPRECATED: "), "en", "pref"), Label(f"CWE-{cwe_id}", "en", "alt")]
            # "Reflected XSS / Non-Persistent XSS / Type 1 XSS" is three names.
            terms = (name for t in el.iter(NS + "Term") if t.text for name in t.text.split(" / "))
            labels += [Label(squash(name), "en", "alt") for name in terms]
            deprecated = status[cwe_id] == "deprecated"
            yield Entry(
                external_id=f"CWE-{cwe_id}",
                url=URL.format(cwe_id),
                title=name,
                kind=kind,
                lang="en",
                status=status[cwe_id],
                replaced_by=replacement(text, status, views) if deprecated else None,
                snippet=text or None,
                # Obsolete stays active: the page is still there, only no longer maintained.
                extra={"type": tag.lower(), "cwe_status": el.get("Status"), "abstraction": el.get("Abstraction")},
                labels=dedupe(labels),
            )

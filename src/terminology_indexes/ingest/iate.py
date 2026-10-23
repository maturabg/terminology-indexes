"""IATE from the public full TBX export, streamed and filtered to EN and BG.

``/em-api/artifacts/full-tbx`` redirects to the export anonymous users can
download (a ZIP with one TBX file of ~1.9 GB). Current exports are an async job
for logged-in users only; see ``docs/decisions.md``.

An entry is kept if it has an EN or BG term that is not ``reliabilityCode`` 1
(not verified). Deprecated and superseded terms are ``redirect`` labels: an
old name still finds the entry. The export has no definitions, so no snippet.
"""

import hashlib
import re
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from terminology_indexes.ingest.base import Adapter, RawSnapshot, download
from terminology_indexes.ingest.text import dedupe, squash
from terminology_indexes.model import Entry, Label

ENTRY_URL = "https://iate.europa.eu/entry/result/"
LANGS = ("en", "bg")
TERM_TYPES = frozenset({"fullForm", "abbreviation", "shortForm"})
UNRELIABLE = "1"
OLD_NAMES = frozenset({"deprecatedTerm-admn-sts", "supersededTerm-admn-sts"})
PREFERRED = "preferredTerm-admn-sts"

XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
_EXPORT_DATE = re.compile(r"IATE_export_(\d{8})\.tbx")


@contextmanager
def open_tbx(path: Path):
    with zipfile.ZipFile(path) as z:
        names = [n for n in z.namelist() if n.endswith(".tbx")]
        if len(names) != 1:
            raise ValueError(f"{path}: expected one TBX file, found {names}")
        with z.open(names[0]) as f:
            yield names[0], f


def export_date(name: str) -> str:
    """``IATE_export_26022019.tbx`` -> ``2019-02-26``."""
    if not (m := _EXPORT_DATE.search(name)):
        return "undated"
    return datetime.strptime(m[1], "%d%m%Y").date().isoformat()


def terms(lang_set: ET.Element) -> list[tuple[int, Label]]:
    """``(order, label)`` of the usable terms of one language; lower order is a better title."""
    lang = lang_set.get(XML_LANG)
    out = []
    for tig in lang_set.iter("tig"):
        text = squash(tig.findtext("term") or "")
        notes = {n.get("type"): n.text for n in tig.iter("termNote")}
        reliability = next((d.text for d in tig.iter("descrip") if d.get("type") == "reliabilityCode"), None)
        if not text or reliability == UNRELIABLE or notes.get("termType", "fullForm") not in TERM_TYPES:
            continue
        status = notes.get("administrativeStatus")
        if status in OLD_NAMES:
            out.append((100, Label(text, lang, "redirect")))
        else:
            # preferred first, then full forms, then abbreviations; then by reliability
            order = 0 if status == PREFERRED else 1 if notes.get("termType", "fullForm") == "fullForm" else 2
            out.append((order * 10 - int(reliability or 0), Label(text, lang, "alt")))
    return out


def domains(el: ET.Element) -> list[str]:
    """IATE domain codes (EuroVoc-based); one ``subjectField`` holds them comma-separated."""
    return [
        code.strip()
        for d in el.iter("descrip")
        if d.get("type") == "subjectField" and d.text
        for code in d.text.split(",")
        if code.strip()
    ]


class Iate(Adapter):
    def fetch(self, raw_dir: Path) -> RawSnapshot:
        path = raw_dir / self.source.id / "iate.zip"
        sha = download(self.source.fetch["url"], path)
        return self.snapshot(path, sha)

    def snapshot(self, path: Path, sha: str | None = None) -> RawSnapshot:
        if sha is None:
            with path.open("rb") as f:
                sha = hashlib.file_digest(f, "sha256").hexdigest()
        with zipfile.ZipFile(path) as z:
            name = next((n for n in z.namelist() if n.endswith(".tbx")), "")
        return RawSnapshot(path=path, sha256=sha, snapshot_version=f"{export_date(name)}+{sha[:12]}")

    def parse(self, snapshot: RawSnapshot) -> Iterator[Entry]:
        with open_tbx(snapshot.path) as (_, f):
            body = None
            for event, el in ET.iterparse(f, events=("start", "end")):
                if event == "start":
                    if el.tag == "body":
                        body = el
                elif el.tag == "termEntry":
                    if entry := self.entry(el):
                        yield entry
                    if body is not None:
                        body.clear()  # a cleared entry still takes memory while attached

    def entry(self, el: ET.Element) -> Entry | None:
        by_lang = {
            ls.get(XML_LANG): sorted(terms(ls), key=lambda t: t[0])
            for ls in el.iter("langSet")
            if ls.get(XML_LANG) in LANGS
        }
        labels: list[Label] = []
        for lang in LANGS:
            found = [label for _, label in by_lang.get(lang, [])]
            if found and found[0].label_type != "redirect":
                found[0] = Label(found[0].label, lang, "pref")
            labels += dedupe(found)
        current = [l for l in labels if l.label_type != "redirect"]
        if not current:
            return None
        iate_id = el.get("id", "").removeprefix("IATE-")
        langs = {l.lang for l in current}
        return Entry(
            external_id=iate_id,
            url=ENTRY_URL + iate_id,
            title=current[0].label,
            kind=self.source.kind_default,
            lang="mul" if len(langs) > 1 else current[0].lang,
            extra={"domain": domains(el)},
            labels=labels,
        )

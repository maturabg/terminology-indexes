"""RFC Editor from ``rfc-index.xml``: one ``document`` per published RFC.

The link is to the RFC's info page, not to a term in it. An obsoleted RFC is
``deprecated``; ``replaced_by`` only when one RFC obsoletes it (RFC 2616 was
split into six).
"""

import re
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from terminology_indexes.ingest.base import Adapter, RawSnapshot, download
from terminology_indexes.ingest.text import dedupe, squash, title_variants
from terminology_indexes.model import Entry, Label

NS = "{https://www.rfc-editor.org/rfc-index}"
URL = "https://www.rfc-editor.org/info/{}/"

_DOC_ID = re.compile(r"(RFC|STD|BCP|FYI)0*(\d+)")


def spaced(doc_id: str) -> str:
    """``RFC9110`` -> ``RFC 9110``, the way RFCs cite each other."""
    return f"{m[1]} {m[2]}" if (m := _DOC_ID.fullmatch(doc_id)) else doc_id


def doc_ids(el: ET.Element, tag: str) -> list[str]:
    parent = el.find(NS + tag)
    return [d.text for d in parent.iter(NS + "doc-id") if d.text] if parent is not None else []


class RfcEditor(Adapter):
    def fetch(self, raw_dir: Path) -> RawSnapshot:
        path = raw_dir / self.source.id / "rfc-index.xml"
        sha = download(self.source.fetch["url"], path)
        return self.snapshot(path, sha)

    def snapshot(self, path: Path, sha: str) -> RawSnapshot:
        # The index has no version; the newest RFC in it says how far it goes.
        last = max((int(m[1]) for m in re.finditer(rb"<doc-id>RFC(\d+)</doc-id>", path.read_bytes())), default=0)
        return RawSnapshot(path=path, sha256=sha, snapshot_version=f"RFC{last}+{sha[:12]}")

    def parse(self, snapshot: RawSnapshot) -> Iterator[Entry]:
        for el in ET.parse(snapshot.path).getroot().iter(NS + "rfc-entry"):
            doc_id = el.findtext(NS + "doc-id") or ""
            title = squash(el.findtext(NS + "title") or "")
            first, *rest = title_variants(title)
            # "Hypertext Transfer Protocol -- HTTP/1.1": both halves are names of the document
            rest += [v for part in title.split(" -- ") if part != title for v in title_variants(part)]
            labels = [Label(first, "en", "pref"), *(Label(v, "en", "alt") for v in rest)]
            labels += [Label(spaced(d), "en", "alt") for d in [doc_id, *doc_ids(el, "is-also")]]
            obsoleted_by = doc_ids(el, "obsoleted-by")
            abstract = el.find(NS + "abstract")
            p = abstract.find(NS + "p") if abstract is not None else None
            extra: dict[str, Any] = {
                "status": el.findtext(NS + "current-status"),
                "stream": el.findtext(NS + "stream"),
                "year": el.findtext(f"{NS}date/{NS}year"),
            }
            if obsoleted_by:
                extra["obsoleted_by"] = obsoleted_by
            yield Entry(
                external_id=doc_id,
                url=URL.format(doc_id.lower()),
                title=f"{spaced(doc_id)}: {title}",
                kind=self.source.kind_default,
                lang="en",
                status="deprecated" if obsoleted_by else "active",
                replaced_by=obsoleted_by[0] if len(obsoleted_by) == 1 else None,
                snippet=squash("".join(p.itertext())) if p is not None else None,
                extra=extra,
                labels=dedupe(labels),
            )

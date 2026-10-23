"""WHATWG and W3C definitions from Webref (branch ``curated``, ``ed/dfns/*.json``).

``fetch`` is a shallow sparse clone of ``ed/dfns/`` and ``ed/index.json`` (the spec
list: organization, standing). Only public, normative, top-level definitions of
term-like types go in; IDL members (``for``) and IDL plumbing stay out.
"""

import hashlib
import json
from collections.abc import Iterator
from pathlib import Path

from terminology_indexes.ingest.base import RawSnapshot
from terminology_indexes.ingest.git_sparse import GitSparse
from terminology_indexes.ingest.text import dedupe, squash
from terminology_indexes.model import Entry, Label

LICENSES = {"WHATWG": "CC BY 4.0", "W3C": "W3C Document License"}
TYPES = frozenset(
    {
        "dfn",
        "interface",
        "property",
        "type",
        "element",
        "selector",
        "function",
        "exception",
        "http-header",
        "event",
        "at-rule",
        "permission",
        "element-attr",
    }
)


def specs(root: Path) -> dict[str, dict]:
    """Shortname -> the fields of ``ed/index.json`` the parser uses, for WHATWG and W3C specs."""
    results = json.loads((root / "ed" / "index.json").read_text(encoding="utf-8"))["results"]
    return {
        r["shortname"]: {"title": r["title"], "organization": r["organization"]}
        for r in results
        if r.get("organization") in LICENSES and r.get("standing") != "discontinued"
    }


class Webref(GitSparse):
    SPARSE = ["/ed/dfns/", "/ed/index.json"]

    def snapshot(self, root: Path) -> RawSnapshot:
        # Hash what the parser reads: the crawl dates in index.json change every day.
        digest = hashlib.sha256(json.dumps(specs(root), sort_keys=True).encode())
        for f in sorted((root / "ed" / "dfns").glob("*.json")):
            digest.update(f.name.encode() + b"\0" + f.read_bytes())
        return self.versioned(root, digest.hexdigest())

    def parse(self, snapshot: RawSnapshot) -> Iterator[Entry]:
        seen: set[str] = set()
        for shortname, spec in sorted(specs(snapshot.path).items()):
            path = snapshot.path / "ed" / "dfns" / f"{shortname}.json"
            if not path.exists():
                continue
            for d in json.loads(path.read_text(encoding="utf-8"))["dfns"]:
                if d["access"] != "public" or d["informative"] or d["for"] or d["type"] not in TYPES:
                    continue
                texts = [squash(t) for t in d["linkingText"] if t.strip()]
                external_id = f"{shortname}#{d['id']}"
                if not texts or external_id in seen:
                    continue
                seen.add(external_id)
                labels = [Label(texts[0], "en", "pref"), *(Label(t, "en", "alt") for t in texts[1:])]
                if d["type"] == "type" and texts[0].startswith("<"):
                    labels.append(Label(texts[0].strip("<>"), "en", "alt"))  # "<color>" is found as "color"
                yield Entry(
                    external_id=external_id,
                    url=d["href"],
                    title=texts[0],
                    kind=self.source.kind_default,
                    lang="en",
                    extra={
                        "spec": shortname,
                        "spec_title": spec["title"],
                        "type": d["type"],
                        "license": LICENSES[spec["organization"]],
                    },
                    labels=dedupe(labels),
                )

"""WHATWG and W3C definitions from Webref (branch ``curated``, ``ed/dfns/*.json``).

``fetch`` is a shallow sparse clone of ``ed/dfns/`` and ``ed/index.json`` (the spec
list: organization, standing). Only public, normative, top-level definitions of
term-like types go in; IDL members (``for``) and IDL plumbing stay out.
"""

import hashlib
import json
import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path

from terminology_indexes.ingest.base import Adapter, RawSnapshot
from terminology_indexes.ingest.text import dedupe, squash
from terminology_indexes.model import Entry, Label

BRANCH = "curated"
SPARSE = ["/ed/dfns/", "/ed/index.json"]
COMMIT_FILE = "webref-commit.json"

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


def git(*args: str, cwd: Path | None = None) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def specs(root: Path) -> dict[str, dict]:
    """Shortname -> the fields of ``ed/index.json`` the parser uses, for WHATWG and W3C specs."""
    results = json.loads((root / "ed" / "index.json").read_text(encoding="utf-8"))["results"]
    return {
        r["shortname"]: {"title": r["title"], "organization": r["organization"]}
        for r in results
        if r.get("organization") in LICENSES and r.get("standing") != "discontinued"
    }


class Webref(Adapter):
    def fetch(self, raw_dir: Path) -> RawSnapshot:
        root = raw_dir / self.source.id
        shutil.rmtree(root, ignore_errors=True)
        root.parent.mkdir(parents=True, exist_ok=True)
        git(
            "clone",
            "-q",
            "--depth",
            "1",
            "--filter=blob:none",
            "--sparse",
            "-b",
            BRANCH,
            self.source.fetch["url"],
            str(root),
        )
        git("sparse-checkout", "set", "--no-cone", *SPARSE, cwd=root)
        commit = {"commit": git("rev-parse", "HEAD", cwd=root), "date": git("log", "-1", "--format=%cs", cwd=root)}
        (root / COMMIT_FILE).write_text(json.dumps(commit), encoding="utf-8")
        return self.snapshot(root)

    def snapshot(self, root: Path) -> RawSnapshot:
        # Hash what the parser reads: the crawl dates in index.json change every day.
        digest = hashlib.sha256(json.dumps(specs(root), sort_keys=True).encode())
        for f in sorted((root / "ed" / "dfns").glob("*.json")):
            digest.update(f.name.encode() + b"\0" + f.read_bytes())
        sha = digest.hexdigest()
        commit = json.loads((root / COMMIT_FILE).read_text(encoding="utf-8"))
        return RawSnapshot(path=root, sha256=sha, snapshot_version=f"{commit['date']}+{commit['commit'][:12]}")

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

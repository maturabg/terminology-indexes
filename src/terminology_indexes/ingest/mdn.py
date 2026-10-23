"""MDN Glossary from ``mdn/content`` (``files/en-us/glossary/**/index.md``).

One page per term; the URL comes from ``slug`` in the frontmatter. Disambiguation
pages ("Boolean") are pages too, their children are "Boolean (JavaScript)" etc.
"""

import re
from collections.abc import Iterator
from pathlib import Path

from terminology_indexes.ingest.base import RawSnapshot
from terminology_indexes.ingest.git_sparse import GitSparse
from terminology_indexes.ingest.markdown import first_paragraph, split_frontmatter
from terminology_indexes.ingest.text import dedupe, heading_labels, title_variants
from terminology_indexes.model import Entry, Label

GLOSSARY = Path("files/en-us/glossary")
BASE = "https://developer.mozilla.org/en-US/docs/"
PAGE_TYPES = frozenset({"glossary-definition", "glossary-disambiguation"})

# {{Glossary("SPA", "single-page apps")}}, {{domxref("XMLHttpRequest")}}, {{GlossaryDisambiguation}}
_MACRO = re.compile(r"\{\{\s*([\w-]+)\s*(?:\((.*?)\))?\s*\}\}")
_STRING_ARG = re.compile(r"\"((?:[^\"\\]|\\.)*)\"|'((?:[^'\\]|\\.)*)'")


def render_macro(m: re.Match) -> str:
    """The link text a macro renders: its second string argument, else its first; banners render nothing."""
    args = [a or b for a, b in _STRING_ARG.findall(m[2] or "")]
    if len(args) > 1 and args[1]:
        return args[1]
    if not args:
        return ""
    text = args[0].replace("/", ".")  # domxref("Window/fetch") shows as Window.fetch
    return text.replace("_", " ") if m[1].lower() == "glossary" else text


class Mdn(GitSparse):
    SPARSE = [f"/{GLOSSARY}/"]

    def files(self, root: Path) -> list[Path]:
        return sorted((root / GLOSSARY).rglob("index.md"))

    def parse(self, snapshot: RawSnapshot) -> Iterator[Entry]:
        for path in self.files(snapshot.path):
            meta, body = split_frontmatter(path.read_text(encoding="utf-8"))
            if meta.get("page-type") not in PAGE_TYPES:
                continue  # the landing page
            slug, title = meta["slug"], meta["title"]
            labels = heading_labels(title)
            if short := meta.get("short-title"):
                labels = dedupe([*labels, *(Label(v, "en", "alt") for v in title_variants(short))])
            yield Entry(
                external_id=slug,
                url=BASE + slug,
                title=title,
                kind=self.source.kind_default,
                lang="en",
                snippet=first_paragraph(_MACRO.sub(render_macro, body)),
                extra={"page_type": meta["page-type"]},
                labels=labels,
            )

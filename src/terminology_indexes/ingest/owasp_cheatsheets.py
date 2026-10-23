"""OWASP Cheat Sheet Series from ``OWASP/CheatSheetSeries`` (``cheatsheets/*.md``).

Each cheat sheet is a ``document``; its ``##`` sections are ``spec_section`` entries
with the anchor MkDocs gives them. Headings shared by several cheat sheets
("Introduction", "References") are page structure, not topics, and stay out.
"""

import re
import unicodedata
from collections import Counter
from collections.abc import Iterator
from pathlib import Path

from terminology_indexes.ingest.base import RawSnapshot
from terminology_indexes.ingest.git_sparse import GitSparse
from terminology_indexes.ingest.markdown import Block, blocks, inline_text
from terminology_indexes.ingest.text import dedupe, heading_labels, title_variants
from terminology_indexes.model import Entry, Label
from terminology_indexes.normalize import term_key

CHEATSHEETS = Path("cheatsheets")
BASE = "https://cheatsheetseries.owasp.org/cheatsheets/"
# A heading in this many cheat sheets or more is boilerplate.
COMMON_HEADING = 3
# Longer headings are sentences ("Why Not Just Fix the Code"), not names.
MAX_SECTION_WORDS = 6

_SUFFIX = re.compile(r"\s+Cheat\s*Sheet\b", re.IGNORECASE)
_HISTORICAL = re.compile(r"\s*\(Historical\)\s*$")
_DEPRECATED = re.compile(r"^DEPRECATED:\s*")
_MD_LINK = re.compile(r"\]\(([\w.-]+)\.md\)")
# "Section 14: Human Accountability", "7. Third-Party Dependencies", "7) Responsibly disclose ..."
_NUMBERING = re.compile(r"^(?:(?:Section|Stage|Step|Part|Rule)\s+)?#?\d+[.:)]?\s*[:.)-]?\s+", re.IGNORECASE)


def slugify(text: str) -> str:
    """Python-Markdown's ``toc`` slug, which MkDocs Material uses for heading ids."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    return re.sub(r"[-\s]+", "-", text)


def anchors(headings: list[Block]) -> list[str]:
    """Ids of all headings in page order; a repeated id gets ``_1``, ``_2`` like ``toc`` does."""
    seen: set[str] = set()
    out = []
    for h in headings:
        base = slug = slugify(inline_text(h.text))
        n = 0
        while slug in seen:
            n += 1
            slug = f"{base}_{n}"
        seen.add(slug)
        out.append(slug)
    return out


def topic(title: str) -> str:
    """``Cross Site Scripting Prevention Cheat Sheet`` -> ``Cross Site Scripting Prevention``."""
    return _SUFFIX.sub("", _HISTORICAL.sub("", _DEPRECATED.sub("", title))).strip()


class OwaspCheatsheets(GitSparse):
    SPARSE = [f"/{CHEATSHEETS}/*.md"]

    def files(self, root: Path) -> list[Path]:
        return sorted((root / CHEATSHEETS).glob("*.md"))

    def parse(self, snapshot: RawSnapshot) -> Iterator[Entry]:
        pages = {p.stem: list(blocks(p.read_text(encoding="utf-8"))) for p in self.files(snapshot.path)}
        per_page = Counter(
            key for bs in pages.values() for key in {term_key(inline_text(b.text)) for b in bs if b.level == 2}
        )
        for stem, bs in pages.items():
            headings = [b for b in bs if b.kind == "heading"]
            if not headings or headings[0].level != 1:
                continue
            title = inline_text(headings[0].text)
            deprecated = bool(_DEPRECATED.match(title) or _HISTORICAL.search(title))
            body = [b for b in bs if b is not headings[0]]
            first = next((inline_text(b.text) for b in body if b.kind == "paragraph"), None)
            replaced_by = None
            if _DEPRECATED.match(title):
                # "Please visit the [Authorization Cheatsheet](Authorization_Cheat_Sheet.md) instead."
                links = (m[1] for b in body if b.kind == "paragraph" for m in _MD_LINK.finditer(b.text))
                replaced_by = next((s for s in links if s != stem and s in pages), None)
            name = topic(title)
            yield Entry(
                external_id=stem,
                url=f"{BASE}{stem}.html",
                title=title,
                kind=self.source.kind_default,
                lang="en",
                status="deprecated" if deprecated else "active",
                replaced_by=replaced_by,
                snippet=first,
                labels=dedupe([Label(name, "en", "pref"), *(Label(v, "en", "alt") for v in title_variants(name)[1:])]),
            )
            if deprecated:
                continue
            for i, (h, anchor) in enumerate(zip(headings, anchors(headings), strict=True)):
                text = inline_text(h.text)
                if h.level != 2 or per_page[term_key(text)] >= COMMON_HEADING or len(text.split()) > MAX_SECTION_WORDS:
                    continue
                start = bs.index(h)
                end = bs.index(headings[i + 1]) if i + 1 < len(headings) else len(bs)
                para = next((inline_text(b.text) for b in bs[start + 1 : end] if b.kind == "paragraph"), None)
                yield Entry(
                    external_id=f"{stem}#{anchor}",
                    url=f"{BASE}{stem}.html#{anchor}",
                    title=text,
                    kind="spec_section",
                    lang="en",
                    snippet=para,
                    extra={"cheatsheet": name},
                    labels=heading_labels(_NUMBERING.sub("", text)),
                )

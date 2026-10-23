"""Markdown helpers for the Git sources (MDN, CNCF, OWASP Cheat Sheets).

Not a Markdown parser: only headings, plain paragraphs and the inline markup a
snippet or a heading anchor needs to lose.
"""

import html
import re
from collections.abc import Iterator
from dataclasses import dataclass

import yaml

from terminology_indexes.ingest.text import squash

_FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n?", re.DOTALL)
_FENCE = re.compile(r"\s*(```|~~~)")
_HEADING = re.compile(r"(#{1,6})\s+(.*?)\s*#*\s*")
# Lines that start something other than a paragraph: lists, quotes, tables, HTML, images.
_NOT_PARAGRAPH = re.compile(r"\s*([-*+]\s|\d+\.\s|>|\||<|!\[)")

_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_EMPHASIS = re.compile(r"(\*\*|__|\*|\b_)(\S(?:.*?\S)?)\1")
_CODE = re.compile(r"`+([^`]*)`+")
_TAG = re.compile(r"</?[a-zA-Z][^<>]*>")


@dataclass(frozen=True)
class Block:
    kind: str  # heading | paragraph
    text: str  # raw Markdown, lines joined with a space
    level: int = 0  # heading level


def split_frontmatter(text: str) -> tuple[dict, str]:
    """``(frontmatter, body)``; no frontmatter gives ``{}``."""
    if m := _FRONTMATTER.match(text):
        return yaml.safe_load(m[1]) or {}, text[m.end() :]
    return {}, text


def blocks(body: str) -> Iterator[Block]:
    """Headings and plain paragraphs, in order; fenced code is skipped entirely."""
    para: list[str] = []
    fence = None

    def flush() -> Iterator[Block]:
        if para:
            yield Block("paragraph", " ".join(para))
            para.clear()

    for line in body.splitlines():
        if fence:
            if line.strip().startswith(fence):
                fence = None
            continue
        if m := _FENCE.match(line):
            yield from flush()
            fence = m[1]
        elif m := _HEADING.fullmatch(line):
            yield from flush()
            yield Block("heading", m[2], len(m[1]))
        elif not line.strip():
            yield from flush()
        elif para:
            para.append(line.strip())
        elif not _NOT_PARAGRAPH.match(line):
            para.append(line.strip())
    yield from flush()


def inline_text(markdown: str) -> str:
    """Plain text of inline Markdown: links keep their text, emphasis and code lose their marks."""
    text = _IMAGE.sub("", markdown)
    text = _LINK.sub(r"\1", text)
    text = _CODE.sub(r"\1", text)
    text = _EMPHASIS.sub(r"\2", text)
    return squash(html.unescape(_TAG.sub("", text)))


def first_paragraph(body: str) -> str | None:
    """Plain text of the first non-empty paragraph."""
    for block in blocks(body):
        if block.kind == "paragraph" and (text := inline_text(block.text)):
            return text
    return None

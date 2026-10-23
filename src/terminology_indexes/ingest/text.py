"""Label helpers shared by the glossary adapters."""

import re
from collections.abc import Iterable

from terminology_indexes.model import Label
from terminology_indexes.normalize import term_key

_SPACES = re.compile(r"\s+")
# "X (Y)" as a whole heading; nested parentheses are left alone.
_PAREN = re.compile(r"(.+?)\s*\(([^()]+)\)")
_ALSO = re.compile(r"also(?: called| known as)?\s+", re.IGNORECASE)
# One token with two capitals or a technical separator: "ROC", "tf.data", "I/O", "pass@k".
_ABBREVIATION = re.compile(r"\S*(?:[A-Z]\S*[A-Z]|[@./_])\S*")
_IDENTIFIER = re.compile(r"\S*[@._]\S*")


def squash(text: str) -> str:
    return _SPACES.sub(" ", text).strip()


def abbreviates(short: str, long: str) -> bool:
    """``short`` is another name of ``long``: a code identifier (``tf.data``), or an acronym
    whose letters, in order, start ``long``'s letters.

    ``AUC`` / ``Area under the ROC curve`` and ``XHR`` / ``XMLHttpRequest`` are; ``DOM`` / ``Node`` is not.
    """
    if _IDENTIFIER.fullmatch(short):
        return True
    letters = [c for c in short.casefold() if c.isalnum()]
    rest = [c for c in long.casefold() if c.isalnum()]
    if not _ABBREVIATION.fullmatch(short) or not letters or not rest or letters[0] != rest[0]:
        return False
    it = iter(rest)
    return all(c in it for c in letters)


def title_variants(title: str) -> list[str]:
    """Search labels for a glossary heading, the heading itself first.

    ``X (Y)`` also gives ``X``; and ``Y`` when it is ``also Y`` or when one side is an
    abbreviation of the other (``AUC (Area under the ROC curve)``, ``Input/Output (I/O)``).
    A qualifier (``node (decision tree)``, ``Node (DOM)``) is not a label of its own.
    """
    title = squash(title)
    variants = [title]
    if m := _PAREN.fullmatch(title):
        base, inner = m[1], m[2]
        variants.append(base)
        if also := _ALSO.match(inner):
            variants.append(inner[also.end() :])
        elif abbreviates(base, inner) or abbreviates(inner, base):
            variants.append(inner)
    return variants


def dedupe(labels: Iterable[Label]) -> list[Label]:
    """Keep the first label per ``term_key``, so the ``pref`` one must come first."""
    seen: set[str] = set()
    out = []
    for label in labels:
        if (key := term_key(label.label)) and key not in seen:
            seen.add(key)
            out.append(label)
    return out


def heading_labels(title: str, lang: str = "en") -> list[Label]:
    """``pref`` for the heading, ``alt`` for the other ``title_variants``."""
    first, *rest = title_variants(title)
    return dedupe([Label(first, lang, "pref"), *(Label(v, lang, "alt") for v in rest)])

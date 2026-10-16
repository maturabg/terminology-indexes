"""Term normalization shared by indexing and search.

Changing any rule here changes ``label_norm`` / ``label_key`` of existing rows:
bump ``NORM_VERSION`` and rebuild every shard.
"""

import re
import unicodedata

NORM_VERSION = 1

# Hyphen-like characters folded into ASCII "-". NFKC already maps U+2011 and
# U+FE58/FE63/FF0D; the rest survive it.
_DASHES = dict.fromkeys(map(ord, "‐‑‒–—―−⁃﹘﹣－"), "-")
_APOSTROPHES = dict.fromkeys(map(ord, "‘’ʼ′"), "'")
_INVISIBLE = dict.fromkeys(map(ord, "­​‌‍⁠﻿"), None)
_TRANSLATE = _DASHES | _APOSTROPHES | _INVISIBLE

_SPACES = re.compile(r"\s+")
_HYPHEN_RUNS = re.compile(r"\s*-\s*")
_KEY_SEPARATORS = re.compile(r"[\s\-_]+")


def normalize_term(text: str) -> str:
    """``label_norm``: NFKC, casefold, one kind of dash, single spaces."""
    text = unicodedata.normalize("NFKC", text).translate(_TRANSLATE).casefold()
    text = _SPACES.sub(" ", text).strip()
    return _HYPHEN_RUNS.sub("-", text)


def term_key(text: str) -> str:
    """``label_key``: ``normalize_term`` without separators (``e-mail`` = ``e mail`` = ``email``)."""
    return _KEY_SEPARATORS.sub("", normalize_term(text))

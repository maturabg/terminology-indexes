import pytest

from terminology_indexes.normalize import normalize_term, term_key


@pytest.mark.parametrize(
    ("raw", "norm"),
    [
        ("Decorator", "decorator"),
        ("  global   interpreter\tlock\n", "global interpreter lock"),
        ("e–mail", "e-mail"),  # en dash
        ("e‑mail", "e-mail"),  # non-breaking hyphen
        ("e−mail", "e-mail"),  # minus sign
        ("e - mail", "e-mail"),
        ("co­operate", "cooperate"),  # soft hyphen
        ("don’t", "don't"),
        ("ＡＰＩ", "api"),  # fullwidth
        ("ﬁle", "file"),  # ligature
        ("Straße", "strasse"),
        ("café", "café"),  # NFKC composes
        ("ПРОМЕНЛИВА", "променлива"),
        ("Йерархия", "йерархия"),  # й stays й
        ("non breaking", "non breaking"),
    ],
)
def test_normalize_term(raw: str, norm: str) -> None:
    assert normalize_term(raw) == norm


@pytest.mark.parametrize("variant", ["email", "e-mail", "e mail", "E-Mail", "e_mail", "e–mail", "e — mail"])
def test_term_key_joins_separators(variant: str) -> None:
    assert term_key(variant) == "email"


def test_term_key_cyrillic() -> None:
    assert term_key("Електронна поща") == term_key("електронна-поща") == "електроннапоща"


def test_term_key_keeps_punctuation_that_is_not_a_separator() -> None:
    assert term_key("__future__") == "future"
    assert term_key("C++") == "c++"
    assert term_key(">>>") == ">>>"


def test_idempotent() -> None:
    for s in ["E–Mail  Address", "Йерархия на класове", "ﬁle-system"]:
        assert normalize_term(normalize_term(s)) == normalize_term(s)

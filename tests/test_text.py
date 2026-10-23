from terminology_indexes.ingest.text import dedupe, heading_labels, title_variants
from terminology_indexes.model import Label


def test_title_variants() -> None:
    assert title_variants("accuracy") == ["accuracy"]
    # abbreviation on either side
    assert title_variants("AUC (Area under the ROC\ncurve)") == [
        "AUC (Area under the ROC curve)",
        "AUC",
        "Area under the ROC curve",
    ]
    assert title_variants("Input/Output (I/O)")[1:] == ["Input/Output", "I/O"]
    assert title_variants("Dataset API (tf.data)")[1:] == ["Dataset API", "tf.data"]
    assert title_variants("commit-ish (also committish)")[1:] == ["commit-ish", "committish"]
    assert title_variants("self-attention (also called self-attention layer)")[2] == "self-attention layer"
    # a qualifier is not a label of its own
    assert title_variants("node (decision tree)") == ["node (decision tree)", "node"]
    assert title_variants("rank (Tensor)") == ["rank (Tensor)", "rank"]
    # only a trailing parenthesis
    assert title_variants("ROC (receiver operating characteristic) Curve") == [
        "ROC (receiver operating characteristic) Curve"
    ]


def test_dedupe_by_term_key() -> None:
    labels = [Label("e-mail", "en", "pref"), Label("E mail", "en", "alt"), Label("email", "en", "alt"), Label("", "en")]
    assert dedupe(labels) == [Label("e-mail", "en", "pref")]
    assert heading_labels("Byte Order Mark (BOM)") == [
        Label("Byte Order Mark (BOM)", "en", "pref"),
        Label("Byte Order Mark", "en", "alt"),
        Label("BOM", "en", "alt"),
    ]


def test_qualifier_is_not_an_abbreviation() -> None:
    # "DOM" looks like an abbreviation but does not abbreviate "Node"
    assert title_variants("Node (DOM)") == ["Node (DOM)", "Node"]
    assert title_variants("Block (CSS)") == ["Block (CSS)", "Block"]
    assert title_variants("XMLHttpRequest (XHR)")[1:] == ["XMLHttpRequest", "XHR"]
    assert title_variants("DSL (Domain-Specific Language)")[1:] == ["DSL", "Domain-Specific Language"]

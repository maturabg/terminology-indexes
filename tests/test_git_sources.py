import shutil
from pathlib import Path

from conftest import DIRECTORIES, load_source, parse_fixture

from terminology_indexes.ingest import get_adapter
from terminology_indexes.ingest.markdown import Block, blocks, first_paragraph, inline_text, split_frontmatter
from terminology_indexes.ingest.owasp_cheatsheets import anchors, slugify


def labels(entry) -> list[tuple[str, str]]:
    return [(l.label, l.label_type) for l in entry.labels]


def test_markdown_helpers() -> None:
    meta, body = split_frontmatter("---\ntitle: X\n---\n\nText\n")
    assert (meta, body) == ({"title": "X"}, "\nText\n")
    assert split_frontmatter("no frontmatter") == ({}, "no frontmatter")
    md = "## Head ##\n```\n# not a heading\n```\n- a list\n> a quote\n\nOne\ntwo\n"
    assert list(blocks(md)) == [Block("heading", "Head", 2), Block("paragraph", "One two")]
    md = "**bold** [`code` link](/x) _em_ snake_case ![img](i.png) &amp;"
    assert inline_text(md) == "bold code link em snake_case &"
    assert first_paragraph("> [!NOTE]\n> skipped\n\n<div>x</div>\n\nFirst.") == "First."


def test_mdn() -> None:
    entries = parse_fixture("mdn")
    # the landing page is not a term; a disambiguation page is
    assert sorted(entries) == [
        "Glossary/AJAX",
        "Glossary/Boolean",
        "Glossary/Boolean/JavaScript",
        "Glossary/Head_of_line_blocking",
        "Glossary/Node/DOM",
    ]
    ajax = entries["Glossary/AJAX"]
    assert ajax.url == "https://developer.mozilla.org/en-US/docs/Glossary/AJAX"
    assert (ajax.title, ajax.kind) == ("Ajax", "term")
    # macros render their link text; banners render nothing
    assert ajax.snippet == (
        "Ajax is a fixture term: a page updates parts of itself with single-page apps techniques,"
        " using Window.fetch or the XMLHttpRequest interface."
    )
    assert entries["Glossary/Boolean"].snippet == "A Boolean is a fixture value that is either true or false."
    assert entries["Glossary/Boolean"].extra == {"page_type": "glossary-disambiguation"}
    hol = entries["Glossary/Head_of_line_blocking"]
    assert labels(hol) == [("Head-of-line blocking", "pref"), ("HOL blocking", "alt")]
    assert hol.snippet == "Fixture text about a queue held up by its first packet (HTTP/2 has it too)."
    # "(DOM)" is a qualifier, not another name of the node
    assert labels(entries["Glossary/Node/DOM"]) == [("Node (DOM)", "pref"), ("Node", "alt")]


def test_cncf_glossary() -> None:
    entries = parse_fixture("cncf_glossary")
    # no _index, _TEMPLATE, search page or draft
    assert sorted(entries) == ["agile-software-development", "application-programming-interface", "hypervisor"]
    api = entries["application-programming-interface"]
    assert api.url == "https://glossary.cncf.io/application-programming-interface/"
    assert labels(api) == [
        ("Application Programming Interface (API)", "pref"),
        ("Application Programming Interface", "alt"),
        ("API", "alt"),
    ]
    assert api.snippet == "An API is a fixture contract between programs. It continues on a second line."
    assert api.extra == {"category": "technology", "status": "Completed"}
    assert entries["hypervisor"].title == "Hypervisor"
    assert entries["agile-software-development"].extra["category"] == ["methodology", "platform"]


def test_owasp_cheatsheets() -> None:
    entries = parse_fixture("owasp_cheatsheets")
    # "Introduction" and "References" are in 3+ cheat sheets; long headings and historical sheets have no sections
    assert sorted(entries) == [
        "Abuse_Case_Cheat_Sheet",
        "Access_Control_Cheat_Sheet",
        "Authorization_Cheat_Sheet",
        "Authorization_Cheat_Sheet#enforce-least-privileges",
        "Clickjacking_Defense_Cheat_Sheet",
        "Clickjacking_Defense_Cheat_Sheet#defending-with-samesite-cookies",
        "Clickjacking_Defense_Cheat_Sheet#section-7-rate-limiting",
        "Clickjacking_Defense_Cheat_Sheet#windowconfirm-protection",
        "Cross_Site_Scripting_Prevention_Cheat_Sheet",
        "Cross_Site_Scripting_Prevention_Cheat_Sheet#output-encoding",
    ]
    xss = entries["Cross_Site_Scripting_Prevention_Cheat_Sheet"]
    assert (xss.url, xss.kind, xss.snippet) == (
        "https://cheatsheetseries.owasp.org/cheatsheets/Cross_Site_Scripting_Prevention_Cheat_Sheet.html",
        "document",
        "This fixture cheat sheet helps prevent XSS.",
    )
    assert labels(xss) == [("Cross Site Scripting Prevention", "pref")]
    section = entries["Cross_Site_Scripting_Prevention_Cheat_Sheet#output-encoding"]
    assert (section.kind, section.snippet, section.extra) == (
        "spec_section",
        "Fixture text about output encoding.",
        {"cheatsheet": "Cross Site Scripting Prevention"},
    )
    assert labels(entries["Clickjacking_Defense_Cheat_Sheet#section-7-rate-limiting"]) == [("Rate Limiting", "pref")]
    access = entries["Access_Control_Cheat_Sheet"]
    assert (access.status, access.replaced_by) == ("deprecated", "Authorization_Cheat_Sheet")
    assert labels(access) == [("Access Control", "pref")]
    abuse = entries["Abuse_Case_Cheat_Sheet"]
    assert (abuse.status, abuse.replaced_by) == ("deprecated", None)


def test_owasp_anchors() -> None:
    # the ids MkDocs gives, checked against cheatsheetseries.owasp.org
    assert slugify("window.confirm() Protection") == "windowconfirm-protection"
    assert slugify("Defending with Content Security Policy (CSP) frame-ancestors directive") == (
        "defending-with-content-security-policy-csp-frame-ancestors-directive"
    )
    heads = [Block("heading", t, 2) for t in ("Introduction", "`Introduction`", "Introduction")]
    assert anchors(heads) == ["introduction", "introduction_1", "introduction_2"]


def test_snapshot_hashes_only_parsed_files(tmp_path: Path) -> None:
    adapter = get_adapter(load_source("cncf_glossary"))
    copy = tmp_path / "cncf_glossary"
    shutil.copytree(DIRECTORIES["cncf_glossary"], copy)
    before = adapter.snapshot(copy)
    assert before.snapshot_version == "2026-10-19+c6493fa4824c"
    (copy / "content" / "en" / "_index.md").write_text("changed")
    assert adapter.snapshot(copy).sha256 == before.sha256
    (copy / "content" / "en" / "hypervisor.md").write_text("changed")
    assert adapter.snapshot(copy).sha256 != before.sha256

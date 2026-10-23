"""OWASP GenAI (WordPress REST), RFC Editor (rfc-index.xml) and NIST DADS (alphabetical index)."""

import io
import json
import shutil
from pathlib import Path

from conftest import DIRECTORIES, RFC_INDEX, load_source, parse_fixture

from terminology_indexes.ingest import get_adapter, owasp_genai
from terminology_indexes.ingest.base import sha256_file


def labels(entry) -> list[tuple[str, str]]:
    return [(l.label, l.label_type) for l in entry.labels]


def test_owasp_genai() -> None:
    entries = parse_fixture("owasp_genai")
    emb = entries["glossaries/embeddings"]
    assert (emb.url, emb.kind) == ("https://genai.owasp.org/glossary/embeddings/", "term")
    # the excerpt repeats the title and ends with "[…]"
    assert emb.snippet == "Embeddings are fixture vectors that place similar items close together."
    rag = entries["glossaries/retrieval-augmented-generation-rag"]
    assert (rag.title, rag.snippet) == ("Retrieval–Augmented Generation (RAG)", None)
    assert ("RAG", "alt") in labels(rag)
    risk = entries["llmrisk/llm01-prompt-injection"]
    assert (risk.kind, risk.extra) == ("concept", {"type": "llmrisk", "risk_id": "LLM01", "edition": "2025"})
    assert labels(risk) == [("Prompt Injection", "pref"), ("LLM01:2025", "alt"), ("LLM01", "alt")]
    assert risk.snippet == "A fixture risk: user input changes the model’s behavior."


def test_owasp_genai_fetch(tmp_path: Path, monkeypatch) -> None:
    """Pages through each post type and writes what ``parse`` reads."""
    fixture = DIRECTORIES["owasp_genai"]
    calls = []

    class Response(io.BytesIO):
        def __init__(self, data: bytes, pages: int) -> None:
            super().__init__(data)
            self.headers = {"X-WP-TotalPages": str(pages)}

        def __enter__(self):
            return self

        def __exit__(self, *exc) -> None:
            pass

    def urlopen(request, timeout):
        url = request.full_url
        calls.append(url)
        post_type = url.removeprefix("https://genai.owasp.org/wp-json/wp/v2/").split("?")[0]
        items = json.loads((fixture / f"{post_type}.json").read_text())
        page = 1 if "page=1&" in url else 2
        # glossaries come in two pages
        if post_type == "glossaries":
            return Response(json.dumps(items[:2] if page == 1 else items[2:]).encode(), 2)
        return Response(json.dumps(items).encode(), 1)

    monkeypatch.setattr(owasp_genai, "robots_allowed", lambda url: True)
    monkeypatch.setattr(owasp_genai.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(owasp_genai.time, "sleep", lambda s: None)
    adapter = get_adapter(load_source("owasp_genai"))
    snapshot = adapter.fetch(tmp_path)
    assert len(calls) == 3
    assert snapshot.sha256 == adapter.snapshot(fixture).sha256
    assert snapshot.snapshot_version.startswith("2026-10-12+")


def test_owasp_genai_snapshot_ignores_modified(tmp_path: Path) -> None:
    adapter = get_adapter(load_source("owasp_genai"))
    copy = tmp_path / "owasp_genai"
    shutil.copytree(DIRECTORIES["owasp_genai"], copy)
    before = adapter.snapshot(copy)
    items = json.loads((copy / "llmrisk.json").read_text())
    items[0]["modified"] = "2026-10-20T00:00:00"
    (copy / "llmrisk.json").write_text(json.dumps(items))
    after = adapter.snapshot(copy)
    assert after.sha256 == before.sha256 and after.snapshot_version != before.snapshot_version


def test_rfc_editor() -> None:
    entries = parse_fixture("rfc_editor")
    # rfc-entry only: no bcp-entry, no rfc-not-issued-entry
    assert sorted(entries) == ["RFC1849", "RFC2119", "RFC2616", "RFC7230", "RFC7540", "RFC8174", "RFC9110", "RFC9113"]
    http = entries["RFC9110"]
    assert (http.url, http.title, http.kind, http.status) == (
        "https://www.rfc-editor.org/info/rfc9110/",
        "RFC 9110: HTTP Semantics",
        "document",
        "active",
    )
    assert labels(http) == [("HTTP Semantics", "pref"), ("RFC 9110", "alt"), ("STD 97", "alt")]
    assert http.snippet.startswith("The Hypertext Transfer Protocol (HTTP) is a stateless application-level protocol")
    assert http.extra == {"status": "INTERNET STANDARD", "stream": "IETF", "year": "2022"}
    # one successor: moved; several: no single replacement
    assert (entries["RFC7540"].status, entries["RFC7540"].replaced_by) == ("deprecated", "RFC9113")
    old = entries["RFC2616"]
    assert (old.status, old.replaced_by) == ("deprecated", None)
    assert old.extra["obsoleted_by"] == ["RFC7230", "RFC7231", "RFC7232", "RFC7233", "RFC7234", "RFC7235"]
    assert ("HTTP/1.1", "alt") in labels(old)
    assert ("BCP 14", "alt") in labels(entries["RFC8174"])


def test_rfc_editor_snapshot() -> None:
    snapshot = get_adapter(load_source("rfc_editor")).snapshot(RFC_INDEX, sha256_file(RFC_INDEX))
    assert snapshot.snapshot_version == f"RFC9113+{snapshot.sha256[:12]}"


def test_nist_dads() -> None:
    entries = parse_fixture("nist_dads")
    # "α: see inverse Ackermann function" alone does not make an entry; the intro link is not in a <dt>
    assert sorted(entries) == [
        "abstractDataType",
        "abtree",
        "ackermann",
        "bktree",
        "bplustree",
        "directAcycGraph",
        "omega",
        "selectkth",
    ]
    dag = entries["directAcycGraph"]
    assert (dag.url, dag.title, dag.snippet) == (
        "https://xlinux.nist.gov/dads/HTML/directAcycGraph.html",
        "directed acyclic graph",
        None,
    )
    assert labels(dag) == [
        ("directed acyclic graph", "pref"),
        ("acyclic directed graph", "redirect"),
        ("DAG", "redirect"),
    ]
    # sub/sup markup and entities become text
    assert [entries[k].title for k in ("bktree", "bplustree", "omega")] == ["Bk tree", "B+-tree", "ω"]
    assert ("selection problem", "redirect") in labels(entries["selectkth"])

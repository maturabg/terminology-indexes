"""CNCF Cloud Native Glossary from ``cncf/glossary`` (``content/en/<slug>.md``).

Hugo builds ``https://glossary.cncf.io/<slug>/`` from every page that is not a
draft. The published sitemap lags behind the repository, so it is not a whitelist.
"""

from collections.abc import Iterator
from pathlib import Path

from terminology_indexes.ingest.base import RawSnapshot
from terminology_indexes.ingest.git_sparse import GitSparse
from terminology_indexes.ingest.markdown import first_paragraph, split_frontmatter
from terminology_indexes.ingest.text import heading_labels, squash
from terminology_indexes.model import Entry

CONTENT = Path("content/en")
BASE = "https://glossary.cncf.io/"


class CncfGlossary(GitSparse):
    SPARSE = [f"/{CONTENT}/*.md"]

    def files(self, root: Path) -> list[Path]:
        # _index.md, _TEMPLATE.md: Hugo sections and templates, not terms
        return sorted(p for p in (root / CONTENT).glob("*.md") if not p.name.startswith("_"))

    def parse(self, snapshot: RawSnapshot) -> Iterator[Entry]:
        for path in self.files(snapshot.path):
            meta, body = split_frontmatter(path.read_text(encoding="utf-8"))
            # search.md has a layout and no category; drafts are not published
            if meta.get("draft") or "category" not in meta or not meta.get("title"):
                continue
            title = squash(meta["title"])
            category = meta["category"]
            yield Entry(
                external_id=path.stem,
                url=f"{BASE}{path.stem}/",
                title=title,
                kind=self.source.kind_default,
                lang="en",
                snippet=first_paragraph(body),
                extra={
                    "category": [c.lower() for c in category] if isinstance(category, list) else category.lower(),
                    "status": squash(meta.get("status") or ""),
                },
                labels=heading_labels(title),
            )

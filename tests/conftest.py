from pathlib import Path

import pytest

from terminology_indexes.model import Source

ROOT = Path(__file__).parent.parent
FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def python_glossary() -> Source:
    return Source.load(ROOT / "sources" / "python_glossary.yaml")

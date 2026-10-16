from conftest import ROOT

from terminology_indexes.ingest import ADAPTERS
from terminology_indexes.model import SNIPPET_LIMITS, load_registry


def test_registry_loads() -> None:
    registry = load_registry(ROOT / "sources")
    assert len(registry) == 28
    for source in registry.values():
        assert source.snippet_policy in SNIPPET_LIMITS
        if source.status == "active":
            assert source.id in ADAPTERS, f"{source.id} is active but has no adapter"

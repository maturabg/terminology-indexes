from conftest import ROOT

from terminology_indexes.ingest import ADAPTERS
from terminology_indexes.model import SNIPPET_LIMITS, load_registry
from terminology_indexes.providers import LIVE_PROVIDERS


def test_registry_loads() -> None:
    registry = load_registry(ROOT / "sources")
    assert len(registry) == 28
    for source in registry.values():
        assert source.snippet_policy in SNIPPET_LIMITS
        if source.status == "active":
            code = LIVE_PROVIDERS if source.mode == "live" else ADAPTERS
            assert source.id in code, f"{source.id} is active but has no adapter or live provider"

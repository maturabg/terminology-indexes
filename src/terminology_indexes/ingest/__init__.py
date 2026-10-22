"""Source adapters: one module per source id."""

from importlib import import_module

from terminology_indexes.ingest.base import Adapter
from terminology_indexes.model import Source

ADAPTERS = {
    "nist_csrc": "terminology_indexes.ingest.nist_csrc:NistCsrc",
    "python_glossary": "terminology_indexes.ingest.python_glossary:PythonGlossary",
}


def get_adapter(source: Source) -> Adapter:
    try:
        target = ADAPTERS[source.id]
    except KeyError:
        raise LookupError(f"no adapter for source {source.id!r}") from None
    module, _, name = target.partition(":")
    return getattr(import_module(module), name)(source)

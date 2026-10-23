"""Source adapters: one module per source id."""

from importlib import import_module

from terminology_indexes.ingest.base import Adapter
from terminology_indexes.model import Source

ADAPTERS = {
    "ecma262": "terminology_indexes.ingest.ecma262:Ecma262",
    "git_glossary": "terminology_indexes.ingest.git_glossary:GitGlossary",
    "google_ml": "terminology_indexes.ingest.google_ml:GoogleMl",
    "mitre_cwe": "terminology_indexes.ingest.mitre_cwe:MitreCwe",
    "nist_csrc": "terminology_indexes.ingest.nist_csrc:NistCsrc",
    "postgresql_glossary": "terminology_indexes.ingest.postgresql_glossary:PostgresqlGlossary",
    "python_glossary": "terminology_indexes.ingest.python_glossary:PythonGlossary",
    "unicode_glossary": "terminology_indexes.ingest.unicode_glossary:UnicodeGlossary",
    "webref": "terminology_indexes.ingest.webref:Webref",
}


def get_adapter(source: Source) -> Adapter:
    try:
        target = ADAPTERS[source.id]
    except KeyError:
        raise LookupError(f"no adapter for source {source.id!r}") from None
    module, _, name = target.partition(":")
    return getattr(import_module(module), name)(source)

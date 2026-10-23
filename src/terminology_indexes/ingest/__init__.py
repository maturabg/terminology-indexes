"""Source adapters: one module per source id."""

from importlib import import_module

from terminology_indexes.ingest.base import Adapter
from terminology_indexes.model import Source

ADAPTERS = {
    "cncf_glossary": "terminology_indexes.ingest.cncf_glossary:CncfGlossary",
    "ecma262": "terminology_indexes.ingest.ecma262:Ecma262",
    "git_glossary": "terminology_indexes.ingest.git_glossary:GitGlossary",
    "google_ml": "terminology_indexes.ingest.google_ml:GoogleMl",
    "mdn": "terminology_indexes.ingest.mdn:Mdn",
    "mitre_cwe": "terminology_indexes.ingest.mitre_cwe:MitreCwe",
    "nist_csrc": "terminology_indexes.ingest.nist_csrc:NistCsrc",
    "nist_dads": "terminology_indexes.ingest.nist_dads:NistDads",
    "owasp_cheatsheets": "terminology_indexes.ingest.owasp_cheatsheets:OwaspCheatsheets",
    "owasp_genai": "terminology_indexes.ingest.owasp_genai:OwaspGenai",
    "postgresql_glossary": "terminology_indexes.ingest.postgresql_glossary:PostgresqlGlossary",
    "python_glossary": "terminology_indexes.ingest.python_glossary:PythonGlossary",
    "rfc_editor": "terminology_indexes.ingest.rfc_editor:RfcEditor",
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

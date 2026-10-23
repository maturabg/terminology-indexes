"""EuroVoc from the latest release's SKOS Core file in Cellar.

The Cellar SPARQL endpoint says which release is the latest and where its
``SKOS_CORE`` manifestation is; the file is a ZIP with one RDF/XML file. Only
concepts of the thesaurus itself (``inScheme`` 100141): the domains ("12 LAW")
are concepts of another scheme, the microthesauri are schemes.
"""

import hashlib
import json
import urllib.parse
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from terminology_indexes.ingest.base import Adapter, RawSnapshot, download
from terminology_indexes.ingest.mediawiki import get_json
from terminology_indexes.ingest.text import dedupe, squash
from terminology_indexes.model import Entry, Label

THESAURUS = "http://eurovoc.europa.eu/100141"
CONCEPT_URL = "https://op.europa.eu/en/web/eu-vocabularies/concept/-/resource?uri="
LANGS = ("en", "bg")

RDF = "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}"
SKOS = "{http://www.w3.org/2004/02/skos/core#}"
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"

# The newest release of the EuroVoc dataset and its SKOS Core manifestation.
LATEST = """
PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>
PREFIX owl: <http://www.w3.org/2002/07/owl#>
SELECT ?version ?date ?manifestation WHERE {
  ?dataset owl:sameAs <http://publications.europa.eu/resource/dataset/eurovoc> .
  ?release cdm:work_is_member_of_complex_work ?dataset ;
           cdm:work_dataset_version ?version ;
           cdm:work_date_document ?date .
  ?expression cdm:expression_belongs_to_work ?release .
  ?manifestation cdm:manifestation_manifests_expression ?expression ;
                 cdm:manifestation_type ?type .
  FILTER (STR(?type) = "SKOS_CORE")
} ORDER BY DESC(?date) LIMIT 1
"""
RELEASE = "release.json"
ARCHIVE = "skos_core.zip"


@contextmanager
def open_rdf(path: Path):
    with zipfile.ZipFile(path) as z:
        names = [n for n in z.namelist() if n.endswith(".rdf")]
        if len(names) != 1:
            raise ValueError(f"{path}: expected one RDF file, found {names}")
        with z.open(names[0]) as f:
            yield f


def texts(el: ET.Element, tag: str, lang: str) -> list[str]:
    return [squash(t.text) for t in el.iter(SKOS + tag) if t.get(XML_LANG) == lang and t.text and t.text.strip()]


class Eurovoc(Adapter):
    def fetch(self, raw_dir: Path) -> RawSnapshot:
        root = raw_dir / self.source.id
        query = urllib.parse.urlencode({"query": LATEST, "format": "application/sparql-results+json"})
        rows = get_json(f"{self.source.fetch['sparql']}?{query}")["results"]["bindings"]
        if not rows:
            raise ValueError("SPARQL found no EuroVoc release with a SKOS_CORE manifestation")
        release = {k: v["value"] for k, v in rows[0].items()}
        # Cellar answers on https too; the manifestation URI is http.
        url = release["manifestation"].replace("http://", "https://", 1) + "/DOC_1"
        download(url, root / ARCHIVE)
        (root / RELEASE).write_text(json.dumps(release, indent=2) + "\n", encoding="utf-8")
        return self.snapshot(root)

    def snapshot(self, root: Path) -> RawSnapshot:
        # Hash the RDF, not the ZIP: a re-packed ZIP of the same release is not a change.
        release = json.loads((root / RELEASE).read_text(encoding="utf-8"))
        digest = hashlib.sha256()
        with open_rdf(root / ARCHIVE) as f:
            while chunk := f.read(1 << 16):
                digest.update(chunk)
        sha = digest.hexdigest()
        return RawSnapshot(path=root, sha256=sha, snapshot_version=f"{release['version']}+{sha[:12]}")

    def parse(self, snapshot: RawSnapshot) -> Iterator[Entry]:
        with open_rdf(snapshot.path / ARCHIVE) as f:
            for _, el in ET.iterparse(f):
                if el.tag != RDF + "Description":
                    continue
                if any(s.get(RDF + "resource") == THESAURUS for s in el.iter(SKOS + "inScheme")):
                    if entry := self.entry(el):
                        yield entry
                el.clear()

    def entry(self, el: ET.Element) -> Entry | None:
        uri = el.get(RDF + "about")
        labels = [Label(t, lang, "pref") for lang in LANGS for t in texts(el, "prefLabel", lang)]
        labels += [Label(t, lang, "alt") for lang in LANGS for t in texts(el, "altLabel", lang)]
        if not labels:
            return None
        definition = texts(el, "definition", "en")
        return Entry(
            external_id=uri,
            url=CONCEPT_URL + uri,
            title=labels[0].label,
            kind=self.source.kind_default,
            lang="mul" if {l.lang for l in labels} == set(LANGS) else labels[0].lang,
            snippet=definition[0] if definition else None,
            extra={"notation": el.findtext(SKOS + "notation")},
            labels=dedupe_per_lang(labels),
        )


def dedupe_per_lang(labels: list[Label]) -> list[Label]:
    """``dedupe`` within each language: an EN and a BG label may share a key ("euro" / "евро" do not, "OECD" may)."""
    return [l for lang in LANGS for l in dedupe(x for x in labels if x.lang == lang)]

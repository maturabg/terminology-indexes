"""Download ``index.sqlite`` from a GitHub release and verify it against its manifest."""

import json
import shutil
import urllib.request
from compression import zstd
from pathlib import Path

from terminology_indexes.ingest.base import TIMEOUT, download, make_request, sha256_file
from terminology_indexes.model import check_schema_version

REPO = "maturabg/terminology-indexes"
API = "https://api.github.com"
ASSETS = ("manifest.json", "index.sqlite.zst")


class ReleaseError(RuntimeError):
    pass


def unpack_index(archive: Path, manifest_path: Path, out: Path) -> Path:
    """Decompress ``index.sqlite.zst`` into ``out``; refuse it on a schema or SHA-256 mismatch."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    check_schema_version(manifest.get("schema_version"), manifest_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".part")
    with zstd.open(archive, "rb") as src, tmp.open("wb") as dst:
        shutil.copyfileobj(src, dst, 1 << 20)
    if (sha := sha256_file(tmp)) != manifest.get("index_sha256"):
        tmp.unlink()
        raise ReleaseError(f"{archive}: sha256 {sha} does not match the manifest")
    tmp.replace(out)
    return out


def download_release(dest: Path | str, *, tag: str | None = None, repo: str = REPO, token: str | None = None) -> Path:
    """Fetch ``manifest.json`` and ``index.sqlite.zst`` of ``tag`` (default: latest) into ``dest``.

    Returns the path of the verified ``index.sqlite``. ``token`` is needed only for a private repo.
    """
    dest = Path(dest)
    url = f"{API}/repos/{repo}/releases/" + (f"tags/{tag}" if tag else "latest")
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    with urllib.request.urlopen(make_request(url, headers, token), timeout=TIMEOUT) as response:
        release = json.load(response)
    assets = {a["name"]: a["url"] for a in release["assets"]}
    if missing := [a for a in ASSETS if a not in assets]:
        raise ReleaseError(f"{release['tag_name']}: missing asset(s) {missing}")
    for name in ASSETS:
        download(assets[name], dest / name, {"Accept": "application/octet-stream"}, token)
    return unpack_index(dest / "index.sqlite.zst", dest / "manifest.json", dest / "index.sqlite")

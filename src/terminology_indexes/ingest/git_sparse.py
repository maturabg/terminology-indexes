"""Base for sources that are part of a Git repository (``fetch.method: git_sparse``).

``fetch`` is a shallow, blobless, sparse clone of ``SPARSE`` from ``fetch.url``
(``fetch.branch`` or the default branch); the commit is kept next to the files.
"""

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

from terminology_indexes.ingest.base import Adapter, RawSnapshot

COMMIT_FILE = "commit.json"


def git(*args: str, cwd: Path | None = None) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def read_commit(root: Path) -> dict[str, str]:
    """``{"commit": <sha>, "date": <YYYY-MM-DD>}`` written by ``fetch``."""
    return json.loads((root / COMMIT_FILE).read_text(encoding="utf-8"))


class GitSparse(Adapter):
    SPARSE: list[str]

    def fetch(self, raw_dir: Path) -> RawSnapshot:
        root = raw_dir / self.source.id
        shutil.rmtree(root, ignore_errors=True)
        root.parent.mkdir(parents=True, exist_ok=True)
        branch = self.source.fetch.get("branch")
        git(
            "clone",
            "-q",
            "--depth",
            "1",
            "--filter=blob:none",
            "--sparse",
            *(["-b", branch] if branch else []),
            self.source.fetch["url"],
            str(root),
        )
        git("sparse-checkout", "set", "--no-cone", *self.SPARSE, cwd=root)
        commit = {"commit": git("rev-parse", "HEAD", cwd=root), "date": git("log", "-1", "--format=%cs", cwd=root)}
        (root / COMMIT_FILE).write_text(json.dumps(commit), encoding="utf-8")
        return self.snapshot(root)

    def files(self, root: Path) -> list[Path]:
        """The files ``parse`` reads, in a stable order; the default hash covers exactly these."""
        raise NotImplementedError

    def snapshot(self, root: Path) -> RawSnapshot:
        # Hash the files, not the commit: most commits touch other parts of the repository.
        digest = hashlib.sha256()
        for f in self.files(root):
            digest.update(f.relative_to(root).as_posix().encode() + b"\0" + f.read_bytes())
        return self.versioned(root, digest.hexdigest())

    @staticmethod
    def versioned(root: Path, sha: str) -> RawSnapshot:
        commit = read_commit(root)
        return RawSnapshot(path=root, sha256=sha, snapshot_version=f"{commit['date']}+{commit['commit'][:12]}")

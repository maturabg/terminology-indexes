"""Search buffer index and source adapters for the en2bg technical dictionary."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("terminology-indexes")
except PackageNotFoundError:
    __version__ = "0.0.0"

# After __version__: ingest.base reads it for the User-Agent.
from terminology_indexes.contract import Candidate, CheckResult, LinkRecord, Provider  # noqa: E402
from terminology_indexes.model import IndexVersionError  # noqa: E402
from terminology_indexes.providers import Registry, load_providers  # noqa: E402
from terminology_indexes.release import ReleaseError, download_release  # noqa: E402

__all__ = [
    "Candidate",
    "CheckResult",
    "IndexVersionError",
    "LinkRecord",
    "Provider",
    "Registry",
    "ReleaseError",
    "download_release",
    "load_providers",
]

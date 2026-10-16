"""Search buffer index and source adapters for the en2bg technical dictionary."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("terminology-indexes")
except PackageNotFoundError:
    __version__ = "0.0.0"

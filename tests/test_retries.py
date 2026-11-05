import io
import subprocess
import urllib.error
from pathlib import Path

import pytest

from terminology_indexes.ingest import base, git_sparse, mediawiki
from terminology_indexes.ingest.base import TemporaryError, download, is_temporary, retrying


@pytest.fixture
def sleeps(monkeypatch) -> list[float]:
    slept: list[float] = []
    monkeypatch.setattr(base.time, "sleep", slept.append)
    return slept


def http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://x", code, "x", {}, None)


def flaky(*results):
    """``call()`` raises or returns the next of ``results``."""
    queue = list(results)

    def call():
        result = queue.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    return call


@pytest.mark.parametrize(
    "error",
    [
        http_error(429),
        http_error(503),
        urllib.error.URLError("Connection refused"),
        TimeoutError(),
        ConnectionResetError(),
        TemporaryError(),
    ],
)
def test_temporary(error) -> None:
    assert is_temporary(error)


@pytest.mark.parametrize(
    "error", [http_error(403), http_error(404), ValueError(), FileNotFoundError(), RuntimeError(), OSError()]
)
def test_not_temporary(error) -> None:
    assert not is_temporary(error)


def test_retrying_recovers(sleeps) -> None:
    assert retrying(flaky(http_error(503), TimeoutError(), "ok")) == "ok"
    assert sleeps == [5, 10]


def test_retrying_gives_up_with_the_last_error(sleeps) -> None:
    with pytest.raises(urllib.error.HTTPError):
        retrying(flaky(*[http_error(503)] * 5))
    assert sleeps == [5, 10, 20, 40]


def test_retrying_does_not_retry_what_needs_a_person(sleeps) -> None:
    with pytest.raises(urllib.error.HTTPError):
        retrying(flaky(http_error(404), "never"))
    assert sleeps == []


def test_download_starts_over_after_a_failure(sleeps, tmp_path: Path, monkeypatch) -> None:
    class Broken(io.BytesIO):
        def read(self, *args) -> bytes:
            if self.tell():
                raise ConnectionResetError
            return super().read(1)

    responses = flaky(Broken(b"xy"), io.BytesIO(b"abc"))
    monkeypatch.setattr("urllib.request.urlopen", lambda request, timeout: responses())
    sha = download("https://x", tmp_path / "out")
    assert (tmp_path / "out").read_bytes() == b"abc"
    assert sha == base.sha256_file(tmp_path / "out")
    assert not (tmp_path / "out.part").exists()


def test_mediawiki_error_answer_is_not_retried(sleeps, monkeypatch) -> None:
    class Response(io.BytesIO):
        headers = {}

    monkeypatch.setattr("urllib.request.urlopen", lambda request, timeout: Response(b'{"error": "bad"}'))
    with pytest.raises(RuntimeError, match="bad"):
        mediawiki.get_json("https://x")
    assert sleeps == []


@pytest.mark.parametrize(
    ("stderr", "temporary"),
    [
        ("fatal: unable to access 'https://x/': Could not resolve host: x", True),
        ("fatal: unable to access 'https://x/': The requested URL returned error: 503", True),
        ("fatal: unable to access 'https://x/': Failed to connect to x port 443", True),
        ("fatal: unable to access 'https://x/': The requested URL returned error: 403", False),
        ("fatal: repository 'https://x/' not found", False),
    ],
)
def test_git_failures(sleeps, monkeypatch, stderr: str, temporary: bool) -> None:
    def run(*args, **kw):
        raise subprocess.CalledProcessError(128, "git", stderr=stderr)

    monkeypatch.setattr(git_sparse.subprocess, "run", run)
    with pytest.raises(Exception, match="git clone: fatal") as e:
        git_sparse.git("clone", "https://x")
    assert is_temporary(e.value) is temporary
    assert len(sleeps) == (4 if temporary else 0)

"""Base of the live providers: HTTP with our User-Agent and the source's rate limit.

A live provider asks its API on every ``search`` / ``check``; ``snapshot_version``
is ``live:<date>``. Network trouble in ``check`` is ``unknown``, never ``dead``.
"""

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from typing import ClassVar

from terminology_indexes.contract import Candidate, CheckResult, LinkRecord
from terminology_indexes.ingest.base import USER_AGENT

TIMEOUT = 20
SHORT = 200  # snippet_policy: short


def short(text: str | None) -> str | None:
    text = " ".join((text or "").split())
    if len(text) > SHORT:
        return text[: SHORT - 1].rstrip() + "…"
    return text or None


class DailyLimitReached(RuntimeError):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None  # a 3xx surfaces as HTTPError with its code and Location


_no_redirect = urllib.request.build_opener(_NoRedirect)


class Http:
    """At most ``rps`` requests a second (shared by threads) and ``daily`` a day."""

    def __init__(self, rps: float, daily: int | None = None) -> None:
        self.interval = 1 / rps
        self.daily = daily
        self._lock = threading.Lock()
        self._next = 0.0
        self._day = date.today()
        self._count = 0

    def _wait(self) -> None:
        with self._lock:
            if (today := date.today()) != self._day:
                self._day, self._count = today, 0
            if self.daily is not None and self._count >= self.daily:
                raise DailyLimitReached(f"{self.daily} requests today")
            self._count += 1
            now = time.monotonic()
            delay = self._next - now
            self._next = max(now, self._next) + self.interval
        if delay > 0:
            time.sleep(delay)

    def request(
        self,
        url: str,
        params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
        *,
        method: str = "GET",
    ) -> urllib.request.Request:
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
        return urllib.request.Request(url, method=method, headers={"User-Agent": USER_AGENT, **(headers or {})})

    def get(self, url: str, params: dict[str, str] | None = None, headers: dict[str, str] | None = None) -> bytes:
        """The body; ``HTTPError`` for 4xx / 5xx."""
        req = self.request(url, params, headers)
        self._wait()
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.read()

    def get_json(self, url: str, params: dict[str, str] | None = None, accept: str = "application/json") -> dict:
        return json.loads(self.get(url, params, {"Accept": accept}))

    def status(
        self, url: str, *, method: str = "HEAD", headers: dict[str, str] | None = None
    ) -> tuple[int, str | None]:
        """Status code and ``Location`` of ``url``, without following redirects."""
        req = self.request(url, method=method)
        self._wait()
        try:
            with _no_redirect.open(req, timeout=TIMEOUT) as r:
                return r.status, None
        except urllib.error.HTTPError as e:
            return e.code, e.headers.get("Location")


def status_result(code: int, location: str | None, url: str) -> CheckResult:
    """The generic rules: 404/410 dead, 301/308 moved, 403/429/5xx unknown."""
    if code in (404, 410):
        return CheckResult("dead", reason=f"HTTP {code}")
    if code in (301, 308) and location:
        return CheckResult("moved", new_url=urllib.parse.urljoin(url, location), reason=f"HTTP {code}")
    if 200 <= code < 400:
        return CheckResult("ok")
    return CheckResult("unknown", reason=f"HTTP {code}")


class LiveProvider:
    """``search`` / ``check`` against an API; subclasses implement ``_check``."""

    id: ClassVar[str]
    api: ClassVar[str]  # = ``live.api`` in the source's yaml
    rps: ClassVar[float] = 1.0  # = ``rate_limit.rps``
    daily: ClassVar[int | None] = None  # = ``rate_limit.daily``
    secret_env: ClassVar[str | None] = None
    live: ClassVar[bool] = True

    def __init__(self, env) -> None:
        self.env = env
        self.http = Http(self.rps, self.daily)

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.id!r})"

    @property
    def snapshot_version(self) -> str:
        return f"live:{date.today().isoformat()}"

    def candidate(self, **fields) -> Candidate:
        return Candidate(source=self.id, snapshot_version=self.snapshot_version, **fields)

    def check(self, link: LinkRecord) -> CheckResult:
        try:
            return self._check(link)
        except urllib.error.HTTPError as e:
            return status_result(e.code, e.headers.get("Location"), link.url)
        except (OSError, DailyLimitReached, ValueError) as e:  # URLError and timeouts are OSError
            return CheckResult("unknown", reason=f"{type(e).__name__}: {e}")

    def _check(self, link: LinkRecord) -> CheckResult:
        raise NotImplementedError

"""Shared HTTP client for the public NLM connectors.

- Outbound allowlist: every request (including redirect hops) must be ``https`` to a known NLM host,
  so an upstream-supplied URL can never make the server fetch an arbitrary address (SSRF).
- Per-host rate limits (NCBI 3/s without a key, MedlinePlus ~85/min, ...), timeouts, retries with
  backoff + jitter, and ``Retry-After`` honoured on 429/503.
- Response bodies are streamed with a size cap.
- Secrets never leave this module: httpx's own request logging is silenced (it prints full URLs,
  including ``api_key=``), our log lines go through :func:`redact`, and failures are re-raised as
  :class:`UpstreamError` carrying only ``host + path`` and the status code, never the query string.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import Iterable
from typing import Any

import httpx
from tenacity import AsyncRetrying, RetryCallState, retry_if_exception, stop_after_attempt, wait_exponential_jitter

logger = logging.getLogger(__name__)
# httpx logs "HTTP Request: GET <full url>" at INFO, which would include NCBI api_key values.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

USER_AGENT = "health-briefing-poc"
_RETRY_STATUS = {429, 500, 502, 503, 504}
MAX_BODY_BYTES = 8 * 1024 * 1024
MAX_RETRY_AFTER_S = 30.0

# Every host the connectors may contact. Source URLs shown to users are validated separately
# (app.schemas.SOURCE_URL_HOSTS).
ALLOWED_HOSTS: frozenset[str] = frozenset(
    {
        "eutils.ncbi.nlm.nih.gov",
        "pubmed.ncbi.nlm.nih.gov",
        "wsearch.nlm.nih.gov",
        "medlineplus.gov",
        "www.nlm.nih.gov",
        "id.nlm.nih.gov",
        "clinicaltables.nlm.nih.gov",
    }
)

# Requests per second per host when the caller passes no limiter of its own.
DEFAULT_HOST_RATES: dict[str, float] = {
    "eutils.ncbi.nlm.nih.gov": 3,
    "wsearch.nlm.nih.gov": 1.2,  # MedlinePlus web service: 85 requests/minute/IP
    "medlineplus.gov": 1.2,
    "id.nlm.nih.gov": 5,
    "clinicaltables.nlm.nih.gov": 5,
}


def redact(url: str) -> str:
    return re.sub(r"(api_key=)[^&]+", r"\1***", url)


class UpstreamError(RuntimeError):
    """An upstream call failed. The message never contains a query string (no secrets)."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class DisallowedHostError(UpstreamError):
    pass


class RateLimiter:
    """Minimum spacing between request starts (e.g. 3/s for NCBI without a key)."""

    def __init__(self, per_second: float) -> None:
        self.interval = 1.0 / per_second
        self._lock = asyncio.Lock()
        self._next = 0.0

    async def wait(self) -> None:
        async with self._lock:
            now = time.monotonic()
            delay = self._next - now
            if delay > 0:
                await asyncio.sleep(delay)
            self._next = max(now, self._next) + self.interval


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in _RETRY_STATUS
    return isinstance(exc, httpx.TransportError)  # includes TimeoutException


def retry_after_seconds(resp: httpx.Response) -> float | None:
    """Delay-seconds form of ``Retry-After`` (the HTTP-date form is ignored), capped."""
    value = resp.headers.get("Retry-After", "").strip()
    if not value:
        return None
    try:
        return max(0.0, min(float(value), MAX_RETRY_AFTER_S))
    except ValueError:
        return None


_backoff = wait_exponential_jitter(initial=0.5, max=8, jitter=0.5)


def _wait(state: RetryCallState) -> float:
    exc = state.outcome.exception() if state.outcome else None
    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in (429, 503):
        after = retry_after_seconds(exc.response)
        if after is not None:
            return after
    return _backoff(state)


def _where(url: httpx.URL) -> str:
    return f"{url.host}{url.path}"


class HttpClient:
    def __init__(
        self,
        timeout_s: float,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        allowed_hosts: Iterable[str] = ALLOWED_HOSTS,
        host_rates: dict[str, float] | None = None,
        max_body_bytes: int = MAX_BODY_BYTES,
    ) -> None:
        self.allowed_hosts = frozenset(allowed_hosts)
        self.max_body_bytes = max_body_bytes
        rates = DEFAULT_HOST_RATES if host_rates is None else host_rates
        self._limiters = {h: RateLimiter(r) for h, r in rates.items()}
        self._client = httpx.AsyncClient(
            timeout=timeout_s,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
            max_redirects=3,
            transport=transport,
            event_hooks={"request": [self._check_request]},  # runs for every redirect hop too
        )

    def set_rate(self, host: str, per_second: float) -> None:
        """Change one host's shared limit (e.g. NCBI 3/s -> 10/s with an API key)."""
        self._limiters[host] = RateLimiter(per_second)

    def is_allowed(self, url: httpx.URL | str) -> bool:
        u = httpx.URL(url) if isinstance(url, str) else url
        return u.scheme == "https" and u.host in self.allowed_hosts

    async def _check_request(self, request: httpx.Request) -> None:
        if not self.is_allowed(request.url):
            raise DisallowedHostError(f"Blocked request to non-allowlisted host {request.url.host or '?'}")

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _fetch(self, url: str, params: dict[str, Any] | None) -> httpx.Response:
        async with self._client.stream("GET", url, params=params) as resp:
            chunks: list[bytes] = []
            size = 0
            async for chunk in resp.aiter_bytes():
                size += len(chunk)
                if size > self.max_body_bytes:
                    raise UpstreamError(f"Response from {_where(resp.request.url)} exceeds {self.max_body_bytes} bytes")
                chunks.append(chunk)
            headers = [
                (k, v) for k, v in resp.headers.items() if k.lower() not in ("content-encoding", "content-length")
            ]
            return httpx.Response(resp.status_code, headers=headers, content=b"".join(chunks), request=resp.request)

    async def get(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        *,
        limiter: RateLimiter | None = None,
        attempts: int = 3,
    ) -> httpx.Response:
        """GET with allowlist, rate limit, retries and a body cap. Raises :class:`UpstreamError` only."""
        target = httpx.URL(url)
        if not self.is_allowed(target):
            raise DisallowedHostError(f"Blocked request to non-allowlisted host {target.host or '?'}")
        limiter = limiter or self._limiters.get(target.host)
        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(attempts),
                wait=_wait,
                retry=retry_if_exception(_is_retryable),
                reraise=True,
            ):
                with attempt:
                    if limiter is not None:
                        await limiter.wait()
                    resp = await self._fetch(url, params)
                    if resp.status_code >= 400:
                        logger.warning("GET %s -> %s", redact(str(resp.request.url)), resp.status_code)
                    resp.raise_for_status()
                    return resp
        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code
            raise UpstreamError(f"HTTP {code} from {_where(exc.request.url)}", status_code=code) from None
        except httpx.HTTPError as exc:
            raise UpstreamError(f"{type(exc).__name__} from {_where(target)}") from None
        raise UpstreamError("unreachable")  # pragma: no cover

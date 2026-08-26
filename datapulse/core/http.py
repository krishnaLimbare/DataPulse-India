"""A polite, reusable HTTP client.

Every source shares this so rate limiting, retries, timeouts, identification
and robots.txt checks are enforced in one place rather than per scraper.
"""

from __future__ import annotations

import threading
import time
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from .logging import get_logger

log = get_logger(__name__)

RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}


def _retry_after_seconds(resp: httpx.Response) -> float | None:
    """Parse a Retry-After header expressed in seconds."""
    try:
        value = float(resp.headers.get("Retry-After", ""))
    except ValueError:
        return None
    return min(value, 120.0) if value > 0 else None


class RobotsDisallowed(RuntimeError):
    """The site's robots.txt forbids this path for our user agent."""


class _RateLimiter:
    """Simple per-client minimum interval between requests (thread safe)."""

    def __init__(self, per_second: float) -> None:
        self._min_interval = 1.0 / per_second if per_second > 0 else 0.0
        self._lock = threading.Lock()
        self._last = 0.0

    def wait(self) -> None:
        if not self._min_interval:
            return
        with self._lock:
            delta = time.monotonic() - self._last
            if delta < self._min_interval:
                time.sleep(self._min_interval - delta)
            self._last = time.monotonic()


class HttpClient:
    def __init__(
        self,
        user_agent: str,
        *,
        rate_limit_per_sec: float = 0.5,
        timeout: float = 30.0,
        max_retries: int = 3,
        respect_robots: bool = True,
        backoff_429: float = 30.0,
    ) -> None:
        self.user_agent = user_agent
        self.respect_robots = respect_robots
        self._limiter = _RateLimiter(rate_limit_per_sec)
        self._max_retries = max_retries
        self._backoff_429 = backoff_429
        self._robots: dict[str, RobotFileParser | None] = {}
        self._client = httpx.Client(
            headers={"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"},
            timeout=timeout,
            follow_redirects=True,
        )

    # -- robots ---------------------------------------------------------
    def _allowed(self, url: str) -> bool:
        if not self.respect_robots:
            return True
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            parser = RobotFileParser()
            try:
                resp = self._client.get(f"{origin}/robots.txt", timeout=10.0)
                parser.parse(resp.text.splitlines() if resp.status_code == 200 else [])
            except httpx.HTTPError:
                parser = None  # unreachable robots.txt -> do not block, but log
                log.warning("robots.txt unreachable for %s; proceeding", origin)
            self._robots[origin] = parser
        parser = self._robots[origin]
        return True if parser is None else parser.can_fetch(self.user_agent, url)

    # -- requests -------------------------------------------------------
    def get(self, url: str, **kwargs) -> httpx.Response:
        if not self._allowed(url):
            raise RobotsDisallowed(url)

        @retry(
            stop=stop_after_attempt(self._max_retries),
            wait=wait_exponential_jitter(initial=1, max=30),
            retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
            reraise=True,
        )
        def _do() -> httpx.Response:
            self._limiter.wait()
            resp = self._client.get(url, **kwargs)
            if resp.status_code == 429:
                # The server is telling us how long to back off; guessing an
                # exponential delay instead just burns the remaining retries.
                delay = _retry_after_seconds(resp) or self._backoff_429
                log.warning("rate limited; sleeping %.0fs before retry", delay)
                time.sleep(delay)
            if resp.status_code in RETRYABLE_STATUS:
                resp.raise_for_status()
            return resp

        return _do()

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> HttpClient:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

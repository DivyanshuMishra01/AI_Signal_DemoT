"""Asynchronous HTTP Client with Bounded Concurrency, Domain Pacing, and 429 Backoff.

Architected to handle massive concurrency without overwhelming target hosts
or triggering automated rate limits.
"""

from __future__ import annotations

import asyncio
import gzip
import logging
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional, Tuple

from frontieratlas.crawler.antibot import AntiBotManager

logger = logging.getLogger(__name__)


class AsyncHTTPClient:
    """Production asynchronous HTTP crawler with pacing, backoff, and jitter."""

    def __init__(
        self,
        max_concurrent_requests: int = 15,
        per_host_limit: int = 3,
        request_timeout: float = 20.0,
        max_retries: int = 3
    ) -> None:
        self.semaphore = asyncio.Semaphore(max_concurrent_requests)
        self.per_host_limit = per_host_limit
        self.request_timeout = request_timeout
        self.max_retries = max_retries

        self._host_semaphores: Dict[str, asyncio.Semaphore] = {}
        self._host_last_access: Dict[str, float] = {}

    def _get_host_semaphore(self, host: str) -> asyncio.Semaphore:
        if host not in self._host_semaphores:
            self._host_semaphores[host] = asyncio.Semaphore(self.per_host_limit)
        return self._host_semaphores[host]

    async def _throttle_host(self, host: str, min_delay: float = 0.2) -> None:
        """Ensure polite pacing between requests to the same domain."""
        now = time.time()
        last = self._host_last_access.get(host, 0.0)
        elapsed = now - last
        if elapsed < min_delay:
            await asyncio.sleep(min_delay - elapsed)
        self._host_last_access[host] = time.time()

    def _fetch_sync(
        self,
        url: str,
        headers: Dict[str, str],
        timeout: float
    ) -> Tuple[int, Dict[str, str], str]:
        """Perform synchronous HTTP request and handle gzip compression."""
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            code = resp.status
            resp_headers = {k.lower(): v for k, v in resp.headers.items()}
            raw_bytes = resp.read()

            # Handle gzip / deflate if present
            if resp_headers.get("content-encoding") == "gzip":
                try:
                    raw_bytes = gzip.decompress(raw_bytes)
                except Exception:
                    pass

            text = raw_bytes.decode("utf-8", errors="replace")
            return code, resp_headers, text

    async def get(
        self,
        url: str,
        custom_headers: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = None
    ) -> Tuple[int, Dict[str, str], str]:
        """Fetch a URL asynchronously with retry, exponential backoff, and host rate limiting."""
        req_timeout = timeout or self.request_timeout
        parsed = urllib.parse.urlsplit(url)
        host = parsed.netloc.lower()

        base_headers = AntiBotManager.get_headers()
        if custom_headers:
            base_headers.update(custom_headers)

        host_sem = self._get_host_semaphore(host)

        for attempt in range(self.max_retries):
            async with self.semaphore:
                async with host_sem:
                    await self._throttle_host(host)
                    try:
                        loop = asyncio.get_running_loop()
                        code, resp_headers, text = await loop.run_in_executor(
                            None, self._fetch_sync, url, base_headers, req_timeout
                        )
                        return code, resp_headers, text

                    except urllib.error.HTTPError as http_err:
                        code = http_err.code
                        if code == 429:
                            # Parse Retry-After header if returned
                            retry_after_hdr = http_err.headers.get("Retry-After")
                            retry_after_val = float(retry_after_hdr) if retry_after_hdr and retry_after_hdr.isdigit() else None
                            
                            # Exponential backoff with full jitter
                            base = min(15.0, 1.5 * (2 ** attempt))
                            sleep_time = (retry_after_val + random.uniform(0.1, 0.5)) if retry_after_val else random.uniform(base * 0.5, base * 1.5)
                            logger.warning(
                                "HTTP 429 for %s (attempt %d/%d). Backing off for %.2fs",
                                url, attempt + 1, self.max_retries, sleep_time
                            )
                            await asyncio.sleep(sleep_time)
                            continue

                        elif code in (500, 502, 503, 504):
                            sleep_time = random.uniform(1.0, 3.0)
                            logger.debug("Server error %d on %s. Retrying in %.2fs", code, url, sleep_time)
                            await asyncio.sleep(sleep_time)
                            continue
                        else:
                            logger.warning("HTTP error %d on %s", code, url)
                            return code, {}, ""

                    except Exception as exc:
                        logger.debug("Fetch error for %s (attempt %d): %s", url, attempt, exc)
                        if attempt == self.max_retries - 1:
                            return 0, {}, ""
                        await asyncio.sleep(random.uniform(0.5, 1.5))

        return 0, {}, ""

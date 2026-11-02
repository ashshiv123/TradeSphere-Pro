"""
http.py — Resilient HTTP client wrapper with retries, exponential backoff, and rate-limit handling.

DATA_PIPELINE_PLAN.md §7.3:
- Timeout: 10s default
- Retries: up to 5 attempts with backoff and jitter
- Handles 429 (Retry-After) and warns on 418 (IP ban) or 451/403 (region block)
"""
from __future__ import annotations

import logging
import random
import time
from typing import Any, Dict, Optional
import httpx

logger = logging.getLogger(__name__)


class ResilientHttpClient:
    """Wrapper around httpx.Client with rate limit backoff and retries."""

    def __init__(self, timeout: float = 10.0, max_retries: int = 5):
        self.timeout = timeout
        self.max_retries = max_retries
        self._client = httpx.Client(timeout=self.timeout, follow_redirects=True)

    def close(self):
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def get(
        self,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> httpx.Response:
        """Execute GET request with exponential backoff and rate-limit handling."""
        attempt = 0
        backoff = 0.5

        while attempt < self.max_retries:
            attempt += 1
            try:
                resp = self._client.get(url, params=params or {}, headers=headers or {})
                status = resp.status_code

                if status == 200:
                    return resp

                if status == 429:
                    retry_after = resp.headers.get("Retry-After")
                    wait_time = float(retry_after) if retry_after else (backoff + random.uniform(0.1, 0.5))
                    logger.warning("HTTP 429 Rate limited on %s. Waiting %.1fs...", url, wait_time)
                    time.sleep(wait_time)
                    backoff *= 2.0
                    continue

                if status == 418:
                    logger.critical("HTTP 418 IP ban received from %s! Halting requests.", url)
                    resp.raise_for_status()

                if status in (403, 451):
                    logger.error("HTTP %d Region block / Forbidden on %s.", status, url)
                    resp.raise_for_status()

                if status >= 500:
                    wait_time = backoff + random.uniform(0.1, 0.5)
                    logger.warning("HTTP %d Server error on %s. Attempt %d/%d. Waiting %.1fs...", status, url, attempt, self.max_retries, wait_time)
                    time.sleep(wait_time)
                    backoff *= 2.0
                    continue

                resp.raise_for_status()

            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                wait_time = backoff + random.uniform(0.1, 0.5)
                logger.warning("Network/Timeout on %s: %s. Attempt %d/%d. Waiting %.1fs...", url, exc, attempt, self.max_retries, wait_time)
                if attempt >= self.max_retries:
                    raise
                time.sleep(wait_time)
                backoff *= 2.0

        raise httpx.RequestError(f"Failed to fetch {url} after {self.max_retries} attempts.")


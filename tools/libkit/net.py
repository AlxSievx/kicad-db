"""Minimal HTTP for the public, keyless part data sources.

Process-wide rate limit of 4 requests per second. Transient failures
(timeouts, connection errors, HTTP 429 and 5xx) are retried up to RETRIES
times with a growing pause; every failure that remains (or a non-retryable
one: other HTTP errors, invalid JSON) becomes a NetError naming the URL.
"""

from __future__ import annotations

import http.client
import json
import time
import urllib.error
import urllib.request

USER_AGENT = "libkit/0.2 (personal KiCad library)"
TIMEOUT = 20
MIN_INTERVAL = 0.25  # seconds between requests: at most 4 per second
RETRIES = 2  # extra attempts after the first one
BACKOFF = (1.0, 3.0)  # pause before retry 1, 2, ... (the last value repeats)

_last = 0.0


class NetError(Exception):
    pass


def _throttle() -> None:
    global _last
    wait = _last + MIN_INTERVAL - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    _last = time.monotonic()


def _retryable(e: Exception) -> bool:
    if isinstance(e, urllib.error.HTTPError):
        return e.code == 429 or e.code >= 500
    return True  # timeouts, refused/reset connections, truncated responses


def _fetch(req: urllib.request.Request, timeout: float, max_bytes: int | None) -> tuple[bytes, str]:
    """Body and Content-Type of `req`, with throttle and retries."""
    url = req.full_url
    for attempt in range(RETRIES + 1):
        _throttle()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read() if max_bytes is None else resp.read(max_bytes + 1)
                ctype = resp.headers.get("Content-Type", "") if getattr(resp, "headers", None) else ""
        except urllib.error.HTTPError as e:
            if attempt < RETRIES and _retryable(e):
                time.sleep(BACKOFF[min(attempt, len(BACKOFF) - 1)])
                continue
            raise NetError(f"{url}: HTTP {e.code}") from e
        except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException) as e:
            if attempt < RETRIES:
                time.sleep(BACKOFF[min(attempt, len(BACKOFF) - 1)])
                continue
            raise NetError(f"{url}: {getattr(e, 'reason', e)}") from e
        if max_bytes is not None and len(body) > max_bytes:
            raise NetError(f"{url}: larger than {max_bytes // 1_000_000} MB")
        return body, ctype
    raise AssertionError("unreachable")


def _request(req: urllib.request.Request) -> dict:
    url = req.full_url
    body, _ = _fetch(req, TIMEOUT, None)
    try:
        data = json.loads(body)
    except (ValueError, UnicodeDecodeError) as e:
        raise NetError(f"{url}: response is not valid JSON") from e
    if not isinstance(data, dict):
        raise NetError(f"{url}: response is not a JSON object")
    return data


def get_json(url: str) -> dict:
    return _request(urllib.request.Request(url, headers={"User-Agent": USER_AGENT}))


def post_json(url: str, body: dict) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"User-Agent": USER_AGENT, "Content-Type": "application/json"},
        method="POST",
    )
    return _request(req)


def get_bytes(url: str, max_bytes: int = 30_000_000, timeout: float = 60) -> tuple[bytes, str]:
    """Raw body and Content-Type of a GET (datasheet PDFs); bodies over max_bytes are a NetError."""
    return _fetch(urllib.request.Request(url, headers={"User-Agent": USER_AGENT}), timeout, max_bytes)

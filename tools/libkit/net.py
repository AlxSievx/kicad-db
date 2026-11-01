"""Minimal JSON-over-HTTP for the public, keyless part data sources.

Process-wide rate limit of 4 requests per second, 20 s timeout. Every failure
(timeout, non-2xx status, invalid JSON) becomes a NetError naming the URL.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

USER_AGENT = "libkit/0.2 (personal KiCad library)"
TIMEOUT = 20
MIN_INTERVAL = 0.25  # seconds between requests: at most 4 per second

_last = 0.0


class NetError(Exception):
    pass


def _throttle() -> None:
    global _last
    wait = _last + MIN_INTERVAL - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    _last = time.monotonic()


def _request(req: urllib.request.Request) -> dict:
    _throttle()
    url = req.full_url
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            body = resp.read()
    except urllib.error.HTTPError as e:
        raise NetError(f"{url}: HTTP {e.code}") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise NetError(f"{url}: {getattr(e, 'reason', e)}") from e
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

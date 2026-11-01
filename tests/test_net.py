import json
import urllib.error

import pytest

from libkit import net


class _Resp:
    def __init__(self, body: bytes, status: int = 200):
        self._body, self.status = body, status

    def read(self, n=-1):
        return self._body if n < 0 else self._body[:n]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_get_json_parses(monkeypatch):
    seen = {}

    def urlopen(req, timeout):
        seen["ua"], seen["timeout"] = req.get_header("User-agent"), timeout
        return _Resp(b'{"a": 1}')
    monkeypatch.setattr(net.urllib.request, "urlopen", urlopen)
    assert net.get_json("https://example.com/x") == {"a": 1}
    assert seen == {"ua": "libkit/0.2 (personal KiCad library)", "timeout": 20}


def test_post_json_sends_body(monkeypatch):
    seen = {}

    def urlopen(req, timeout):
        seen["body"] = json.loads(req.data)
        seen["ct"] = req.get_header("Content-type")
        return _Resp(b'{"ok": true}')
    monkeypatch.setattr(net.urllib.request, "urlopen", urlopen)
    assert net.post_json("https://example.com/x", {"k": "v"}) == {"ok": True}
    assert seen == {"body": {"k": "v"}, "ct": "application/json"}


@pytest.mark.parametrize("exc", [
    urllib.error.HTTPError("https://example.com/x", 500, "boom", {}, None),
    urllib.error.URLError("unreachable"),
    TimeoutError("timed out"),
])
def test_errors_become_neterror(monkeypatch, exc):
    def urlopen(req, timeout):
        raise exc
    monkeypatch.setattr(net.urllib.request, "urlopen", urlopen)
    with pytest.raises(net.NetError, match="example.com"):
        net.get_json("https://example.com/x")


def test_invalid_json_is_neterror(monkeypatch):
    monkeypatch.setattr(net.urllib.request, "urlopen", lambda req, timeout: _Resp(b"<html>"))
    with pytest.raises(net.NetError, match="JSON"):
        net.get_json("https://example.com/x")


def test_rate_limit(monkeypatch):
    clock = {"t": 100.0}
    sleeps = []
    monkeypatch.setattr(net.time, "monotonic", lambda: clock["t"])
    monkeypatch.setattr(net.time, "sleep", lambda s: (sleeps.append(s), clock.__setitem__("t", clock["t"] + s)))
    monkeypatch.setattr(net, "_last", 0.0)
    monkeypatch.setattr(net, "MIN_INTERVAL", 0.25)  # conftest turns the limit off
    monkeypatch.setattr(net.urllib.request, "urlopen", lambda req, timeout: _Resp(b"{}"))
    net.get_json("https://example.com/1")
    net.get_json("https://example.com/2")
    assert sleeps and abs(sum(sleeps) - 0.25) < 1e-9

def _flaky(monkeypatch, failures, body=b'{"ok": 1}'):
    """urlopen that raises each exception in `failures` once, then answers."""
    calls = []

    def urlopen(req, timeout):
        calls.append(req.full_url)
        if len(calls) <= len(failures):
            raise failures[len(calls) - 1]
        return _Resp(body)
    monkeypatch.setattr(net.urllib.request, "urlopen", urlopen)
    return calls


def _http(code):
    return urllib.error.HTTPError("https://example.com/x", code, "x", {}, None)


@pytest.mark.parametrize("exc", [_http(500), _http(503), _http(429), urllib.error.URLError("reset"),
                                 TimeoutError("timed out")])
def test_transient_errors_are_retried(monkeypatch, exc):
    calls = _flaky(monkeypatch, [exc])
    assert net.get_json("https://example.com/x") == {"ok": 1}
    assert len(calls) == 2


def test_retries_give_up(monkeypatch):
    calls = _flaky(monkeypatch, [_http(500)] * 10)
    with pytest.raises(net.NetError, match="HTTP 500"):
        net.get_json("https://example.com/x")
    assert len(calls) == net.RETRIES + 1


@pytest.mark.parametrize("code", [400, 403, 404])
def test_client_errors_are_not_retried(monkeypatch, code):
    calls = _flaky(monkeypatch, [_http(code)] * 10)
    with pytest.raises(net.NetError, match=f"HTTP {code}"):
        net.get_json("https://example.com/x")
    assert len(calls) == 1


def test_invalid_json_is_not_retried(monkeypatch):
    calls = _flaky(monkeypatch, [], body=b"<html>")
    with pytest.raises(net.NetError, match="JSON"):
        net.get_json("https://example.com/x")
    assert len(calls) == 1


def test_retry_pauses(monkeypatch):
    sleeps = []
    monkeypatch.setattr(net, "BACKOFF", (1.0, 3.0))
    monkeypatch.setattr(net, "MIN_INTERVAL", 0)
    monkeypatch.setattr(net.time, "sleep", sleeps.append)
    _flaky(monkeypatch, [_http(502), _http(502)])
    net.get_json("https://example.com/x")
    assert sleeps == [1.0, 3.0]


def test_get_bytes(monkeypatch):
    class R(_Resp):
        headers = {"Content-Type": "application/pdf"}
    monkeypatch.setattr(net.urllib.request, "urlopen", lambda req, timeout: R(b"%PDF-1.4 x"))
    assert net.get_bytes("https://example.com/a.pdf") == (b"%PDF-1.4 x", "application/pdf")


def test_get_bytes_size_limit(monkeypatch):
    monkeypatch.setattr(net.urllib.request, "urlopen", lambda req, timeout: _Resp(b"x" * 101))
    with pytest.raises(net.NetError, match="larger than"):
        net.get_bytes("https://example.com/a.pdf", max_bytes=100)

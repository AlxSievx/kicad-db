import json
import urllib.error

import pytest

from libkit import net


class _Resp:
    def __init__(self, body: bytes, status: int = 200):
        self._body, self.status = body, status

    def read(self):
        return self._body

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
    monkeypatch.setattr(net.urllib.request, "urlopen", lambda req, timeout: _Resp(b"{}"))
    net.get_json("https://example.com/1")
    net.get_json("https://example.com/2")
    assert sleeps and abs(sum(sleeps) - 0.25) < 1e-9

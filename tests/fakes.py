"""Offline stand-ins for the network, built from recorded responses."""

from __future__ import annotations

import json
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"


def load(rel: str) -> dict:
    return json.loads((FIXTURES / rel).read_text(encoding="utf-8"))


def rec(code: str) -> dict:
    """The JLC record for one C-number from tests/fixtures/jlc/<code>.json."""
    lst = load(f"jlc/{code}.json")["data"]["componentPageInfo"]["list"]
    return next(r for r in lst if r["componentCode"] == code)


def fake_post(fname: str):
    """A post_json replacement that always answers with one recorded JLC response."""
    def post(url, body):
        return load(f"jlc/{fname}")
    return post


def fake_get(fname: str):
    """A get_json replacement that always answers with one recorded jlcsearch response."""
    def get(url):
        return load(f"jlcsearch/{fname}")
    return get

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


ENGLISH = ("This datasheet is for the general series of chip resistors. The parts are suitable for "
           "reflow soldering and are used in consumer and industrial equipment. Refer to the notes "
           "on storage and handling of the reels before use, and to the test methods of this series.")


def pdf_bytes(text: str = ENGLISH) -> bytes:
    """A minimal one-page PDF showing `text` in Helvetica (Latin text only)."""
    words, lines, line = text.split(), [], ""
    for w in words:
        if len(line) + len(w) > 70:
            lines.append(line)
            line = ""
        line = f"{line} {w}".strip()
    lines.append(line)
    esc = [ln.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") for ln in lines]
    content = ("BT /F1 11 Tf 14 TL 72 720 Td " + " ".join(f"({ln}) Tj T*" for ln in esc) + " ET").encode("latin-1")
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R"
        b" /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return bytes(out)


def fake_get_bytes(body: bytes | None = None, calls: list | None = None):
    """A net.get_bytes replacement answering every URL with one PDF (English by default)."""
    body = pdf_bytes() if body is None else body

    def get(url, **kw):
        if calls is not None:
            calls.append(url)
        return body, "application/pdf"
    return get


def fake_get(fname: str):
    """A get_json replacement that always answers with one recorded jlcsearch response."""
    def get(url):
        return load(f"jlcsearch/{fname}")
    return get


def paged_fake(fname: str):
    """A post_json replacement for keyword searches: page 1 comes from
    tests/fixtures/jlc/<fname>; asking for any later page fails the test."""
    def post(url, body):
        assert body.get("currentPage") == 1, f"unexpected request for page {body.get('currentPage')}"
        return load(f"jlc/{fname}")
    return post

import json
import os

import pytest

from fakes import ENGLISH, fake_get_bytes, pdf_bytes
from libkit import datasheet
from libkit.datasheet import CACHE_FILE, Checker, Result, classify, fetch_pdf, language, pdf_text
from libkit.net import NetError

CHINESE = "通用型系列片式陶瓷电容器具有优良的焊接与耐焊性能适用于回流焊接与波峰焊接" * 3 + " 0402 X7R 100nF 16V"
BILINGUAL = "产品规格书 PRODUCT SPECIFICATION 特征 " + ENGLISH + " " + CHINESE


@pytest.mark.parametrize("text, lang", [
    (ENGLISH, "en"),
    (BILINGUAL, "en"),  # Chinese/English datasheets are readable in English
    (CHINESE, "zh"),
    ("CL05B104KO5NNNC 0402 X7R 16V 100nF 1.0x0.5 mm", "unknown"),  # a drawing: no prose either way
    ("", "unknown"),
])
def test_classify(text, lang):
    assert classify(text) == lang


def test_pdf_text_reads_the_fake_pdf():
    assert "reflow soldering" in pdf_text(pdf_bytes())


def test_fetch_pdf_direct():
    assert fetch_pdf("https://x/a.pdf", get=fake_get_bytes()) == pdf_bytes()


def test_fetch_pdf_follows_lcsc_viewer_page():
    # www.lcsc.com/datasheet/... is an HTML page that links the PDF on datasheet.lcsc.com
    pdf_url = "https://datasheet.lcsc.com/datasheet/pdf/02336ea48ea44ca18c72517dd3cb7b47.pdf?productCode=C1525"
    seen = []

    def get(url, **kw):
        seen.append(url)
        if url == pdf_url:
            return pdf_bytes(), "application/pdf"
        return f'<html><iframe src="viewer.html?file=x"></iframe><a href="{pdf_url}">PDF</a></html>'.encode(), "text/html"
    assert fetch_pdf("https://www.lcsc.com/datasheet/C1525.pdf", get=get) == pdf_bytes()
    assert seen == ["https://www.lcsc.com/datasheet/C1525.pdf", pdf_url]


def test_fetch_pdf_none_when_page_has_no_pdf():
    # A missing LCSC datasheet redirects to the shop's home page.
    assert fetch_pdf("https://www.lcsc.com/datasheet/C1017.pdf",
                     get=fake_get_bytes(b"<!DOCTYPE html><html>LCSC home</html>")) is None


def test_language_english():
    assert language("https://x/a.pdf", get=fake_get_bytes()) == Result("en")


def test_language_no_text_is_unknown():
    r = language("https://x/a.pdf", get=fake_get_bytes(pdf_bytes("0402 X7R 16V")))
    assert r.lang == "unknown" and "no readable text" in r.note and not r.transient


@pytest.mark.parametrize("body, note", [
    (b"<html></html>", "no PDF behind the link"),
    (b"%PDF-1.4\nthis is not really a PDF", ""),
])
def test_language_broken_is_unknown(body, note):
    r = language("https://x/a.pdf", get=fake_get_bytes(body))
    assert r.lang == "unknown" and note in r.note and not r.transient


def test_language_download_failure_is_transient():
    def get(url, **kw):
        raise NetError(f"{url}: HTTP 503")
    r = language("https://x/a.pdf", get=get)
    assert r.lang == "unknown" and "HTTP 503" in r.note and r.transient


def test_language_without_link():
    assert language("").note == "no datasheet link"


def test_checker_caches_per_url(tmp_path):
    calls = []
    c = Checker(tmp_path, get=fake_get_bytes(calls=calls))
    assert c.check("https://x/a.pdf").lang == "en"
    assert c.check("https://x/a.pdf").lang == "en"
    assert calls == ["https://x/a.pdf"]
    # persisted: a new Checker answers without downloading
    calls.clear()
    assert Checker(tmp_path, get=fake_get_bytes(calls=calls)).check("https://x/a.pdf").lang == "en"
    assert calls == []
    assert json.loads((tmp_path / CACHE_FILE).read_text(encoding="utf-8"))["https://x/a.pdf"]["lang"] == "en"


def test_checker_does_not_cache_download_failures(tmp_path):
    def down(url, **kw):
        raise NetError("offline")
    assert Checker(tmp_path, get=down).check("https://x/a.pdf").transient
    assert not (tmp_path / CACHE_FILE).exists()
    assert Checker(tmp_path, get=fake_get_bytes()).check("https://x/a.pdf").lang == "en"


def test_checker_ignores_a_broken_cache(tmp_path):
    (tmp_path / CACHE_FILE).parent.mkdir()
    (tmp_path / CACHE_FILE).write_text("[not json", encoding="utf-8")
    assert Checker(tmp_path, get=fake_get_bytes()).check("https://x/a.pdf").lang == "en"


def test_checker_for_part_uses_lcsc_fallback(tmp_path):
    from libkit.jlc import JlcPart
    calls = []
    part = JlcPart("C1525", "CL05B104KO5NNNC", "Samsung", "0402", 1, "Basic", "", "", {})
    Checker(tmp_path, get=fake_get_bytes(calls=calls)).for_part(part)
    assert calls == ["https://www.lcsc.com/datasheet/C1525.pdf"]


def test_default_download_goes_through_net(monkeypatch):
    # The conftest blocks real network access: the check reports it, never raises.
    r = datasheet.language("https://www.lcsc.com/datasheet/C1525.pdf")
    assert r.lang == "unknown" and r.transient and "network disabled" in r.note


@pytest.mark.skipif(os.environ.get("LIBKIT_LIVE") != "1", reason="live network test")
@pytest.mark.parametrize("lcsc, lang", [
    ("C25744", "en"),  # UNI-ROYAL resistor
    ("C1545", "en"),  # FH capacitor: bilingual
    ("C14267", "zh"),  # WCH CH340G: Chinese only
])
def test_live_language(tmp_path, lcsc, lang):
    from libkit.jlc import lookup
    assert Checker(tmp_path).for_part(lookup(lcsc)).lang == lang

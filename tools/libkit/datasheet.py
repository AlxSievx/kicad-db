"""Datasheet language check: English datasheets are preferred (CLAUDE.md, selection rule 6).

language() downloads the PDF behind a datasheet link and classifies the text
of its first pages:

  en       English prose; bilingual Chinese/English datasheets count as English
  zh       CJK text without English prose
  unknown  no text layer (scanned drawing), no PDF behind the link, unreadable
           PDF, or the download failed

The test is deliberately simple: English prose is full of a few short words
("the", "and", "of", ...), while a Chinese-only datasheet has CJK text and
almost none of them (part numbers and units are Latin in both). Calibrated
on LCSC datasheets of UNI-ROYAL, Samsung, Yageo, FH, WCH, TI and others.

Checker caches results per URL in .libkit/datasheet-lang.json under the
library root (not committed); failed downloads are not cached.
"""

from __future__ import annotations

import io
import json
import logging
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from . import net
from .jlc import JlcPart, datasheet_url
from .net import NetError

LANGS = ("en", "zh", "unknown")
PAGES = 4  # pages of text read per datasheet
MIN_STOPWORDS = 15  # English stopwords in those pages to call it English
MIN_CJK = 50  # CJK characters to call it Chinese (when not English)
CACHE_FILE = Path(".libkit") / "datasheet-lang.json"

STOPWORDS = frozenset({"the", "and", "of", "for", "with", "to", "is", "are", "in", "be",
                       "or", "at", "by", "this", "on", "not"})
_WORD = re.compile(r"[A-Za-z]+")
_CJK = re.compile(r"[぀-ヿ㐀-䶿一-鿿豈-﫿]")
# www.lcsc.com/datasheet/... answers with an HTML viewer page; the PDF itself
# lives on datasheet.lcsc.com and is linked from that page.
_LCSC_PDF = re.compile(rb"https://datasheet\.lcsc\.com/datasheet/pdf/[0-9a-f]+\.pdf(?:\?productCode=C\d+)?")


@dataclass(frozen=True)
class Result:
    lang: str  # one of LANGS
    note: str = ""  # why, when lang is "unknown"
    transient: bool = False  # a network failure: worth asking again later


def classify(text: str) -> str:
    """"en", "zh" or "unknown" for the extracted text of a datasheet."""
    words = _WORD.findall(text.lower())
    if sum(w in STOPWORDS for w in words) >= MIN_STOPWORDS:
        return "en"
    if len(_CJK.findall(text)) >= MIN_CJK:
        return "zh"
    return "unknown"


def _is_pdf(body: bytes) -> bool:
    return b"%PDF-" in body[:1024]


def fetch_pdf(url: str, get=None) -> bytes | None:
    """The PDF behind a datasheet link (following LCSC's viewer page), or None."""
    get = get or net.get_bytes
    body, _ = get(url)
    if _is_pdf(body):
        return body
    m = _LCSC_PDF.search(body)
    if m is None:
        return None
    body, _ = get(m.group(0).decode("ascii"))
    return body if _is_pdf(body) else None


def pdf_text(data: bytes, pages: int = PAGES) -> str:
    import pypdf
    logging.getLogger("pypdf").setLevel(logging.CRITICAL)  # malformed-but-readable PDFs are common
    reader = pypdf.PdfReader(io.BytesIO(data))  # tries the empty password on encrypted PDFs
    return "\n".join(page.extract_text() or "" for page in reader.pages[:pages])


def language(url: str, get=None) -> Result:
    if not url:
        return Result("unknown", "no datasheet link")
    try:
        data = fetch_pdf(url, get)
    except NetError as e:
        return Result("unknown", f"download failed: {e}", transient=True)
    if data is None:
        return Result("unknown", "no PDF behind the link")
    try:
        text = pdf_text(data)
    except Exception as e:  # noqa: BLE001 - pypdf raises many kinds of errors on broken files
        return Result("unknown", f"unreadable PDF ({type(e).__name__})")
    lang = classify(text)
    return Result(lang, "no readable text (scan or drawing?)" if lang == "unknown" else "")


class Checker:
    """language() with a per-URL cache in <root>/.libkit/datasheet-lang.json."""

    def __init__(self, root: Path, get=None):
        self.path = Path(root) / CACHE_FILE
        self.get = get
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            self.cache = {u: Result(**r) for u, r in raw.items()}
        except (OSError, ValueError, TypeError, AttributeError):
            self.cache = {}

    def check(self, url: str) -> Result:
        if url in self.cache:
            return self.cache[url]
        r = language(url, self.get)
        if not r.transient:
            self.cache[url] = r
            self._save()
        return r

    def for_part(self, part: JlcPart) -> Result:
        return self.check(datasheet_url(part))

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({u: asdict(r) for u, r in sorted(self.cache.items())}, indent=1),
                       encoding="utf-8")
        tmp.replace(self.path)

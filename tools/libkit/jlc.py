"""JLCPCB parts search: the authoritative record for one LCSC C-number."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import net
from .net import NetError

SEARCH_URL = "https://jlcpcb.com/api/overseas-pcb-order/v1/shoppingCart/smtGood/selectSmtComponentList"


@dataclass
class JlcPart:
    lcsc: str
    mpn: str
    brand: str
    package: str
    stock: int
    jlc_type: str  # "Basic" | "Preferred" | "Extended"
    datasheet: str
    description: str
    attributes: dict[str, str] = field(default_factory=dict)
    type_name: str = ""  # componentTypeEn, e.g. "Schottky Diodes"


def datasheet_url(part: JlcPart) -> str:
    """JLC's datasheet link, or LCSC's generic one when JLC has none (CLAUDE.md)."""
    return part.datasheet or f"https://www.lcsc.com/datasheet/{part.lcsc}.pdf"


def _jlc_type(rec: dict) -> str:
    if rec.get("preferredComponentFlag"):
        return "Preferred"
    return "Basic" if rec.get("componentLibraryType") == "base" else "Extended"


def parse_record(rec: dict) -> JlcPart:
    code = rec.get("componentCode", "?")
    try:
        return JlcPart(
            lcsc=str(rec["componentCode"]),
            mpn=str(rec["componentModelEn"]),
            brand=str(rec["componentBrandEn"]),
            package=str(rec["componentSpecificationEn"]),
            stock=int(rec["stockCount"]),
            jlc_type=_jlc_type(rec),
            datasheet=str(rec.get("dataManualUrl") or ""),
            description=str(rec.get("describe") or ""),
            attributes={str(a["attribute_name_en"]): str(a["attribute_value_name"])
                        for a in rec.get("attributes") or []},
            type_name=str(rec.get("componentTypeEn") or ""),
        )
    except (KeyError, TypeError, ValueError) as e:
        raise NetError(f"{code}: unexpected JLC record format ({e!r})") from e


def lookup(lcsc: str, post=None) -> JlcPart | None:
    """The JLC record whose componentCode is exactly `lcsc`, or None."""
    post = post or net.post_json
    try:
        data = post(SEARCH_URL, {"keyword": lcsc, "currentPage": 1, "pageSize": 5})
    except NetError as e:
        # The C-number is in the POST body, not the URL: name it.
        raise NetError(f"{lcsc}: {e}") from e
    for rec in _records(data, lcsc):
        if isinstance(rec, dict) and rec.get("componentCode") == lcsc:
            return parse_record(rec)
    return None


PAGE_SIZE = 100
_C_NUMBER = re.compile(r"C\d+")


def _records(data: dict, what: str) -> list:
    try:
        records = data["data"]["componentPageInfo"]["list"] or []
        if not isinstance(records, list):
            raise TypeError("list is not a list")
    except (KeyError, TypeError) as e:
        raise NetError(f"{what}: unexpected JLC response format ({e!r})") from e
    return records


MAX_RESOLVE_PAGES = 10


def _search(keyword: str, pages: int, post) -> tuple[list[JlcPart], bool]:
    """(parts, complete): complete is False when more results exist than were read."""
    post = post or net.post_json
    out: list[JlcPart] = []
    for page in range(1, pages + 1):
        try:
            data = post(SEARCH_URL, {"keyword": keyword, "currentPage": page, "pageSize": PAGE_SIZE})
        except NetError as e:
            raise NetError(f"search {keyword!r}: {e}") from e
        records = _records(data, f"search {keyword!r}")
        out += [parse_record(r) for r in records if isinstance(r, dict)]
        total = (data.get("data") or {}).get("componentPageInfo", {}).get("total")
        if len(records) < PAGE_SIZE or (isinstance(total, int) and page * PAGE_SIZE >= total):
            return out, True
    return out, False


def search(keyword: str, *, pages: int = 3, post=None) -> list[JlcPart]:
    """JLC keyword search (e.g. "10uH 0805" or an MPN), up to `pages` pages of 100.

    Results come in C-number order, not by stock or type; callers sort."""
    return _search(keyword, pages, post)[0]


def resolve(ref: str, post=None) -> JlcPart:
    """The JLC part for an LCSC C-number or an exact MPN (case-insensitive)."""
    ref = ref.strip()
    if _C_NUMBER.fullmatch(ref.upper()):
        part = lookup(ref.upper(), post=post)
        if part is None:
            raise ValueError(f"{ref.upper()}: not found at JLC")
        return part
    found, complete = _search(ref, MAX_RESOLVE_PAGES, post)
    if not complete:
        raise ValueError(f"MPN {ref!r} gives more than {MAX_RESOLVE_PAGES * PAGE_SIZE} JLC results, so "
                         "other exact matches may exist; use the C-number")
    hits = [p for p in found if p.mpn.casefold() == ref.casefold()]
    if not hits:
        raise ValueError(f"no JLC part with MPN {ref!r}; use the C-number")
    if len(hits) > 1:
        listed = ", ".join(f"{p.lcsc} ({p.brand}, stock {p.stock}, {p.jlc_type})" for p in hits)
        raise ValueError(f"MPN {ref!r} matches several JLC parts: {listed}; use the C-number")
    return hits[0]

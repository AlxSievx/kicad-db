"""JLCPCB parts search: the authoritative record for one LCSC C-number."""

from __future__ import annotations

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
    try:
        records = data["data"]["componentPageInfo"]["list"] or []
        if not isinstance(records, list):
            raise TypeError("list is not a list")
    except (KeyError, TypeError) as e:
        raise NetError(f"{lcsc}: unexpected JLC response format ({e!r})") from e
    for rec in records:
        if isinstance(rec, dict) and rec.get("componentCode") == lcsc:
            return parse_record(rec)
    return None

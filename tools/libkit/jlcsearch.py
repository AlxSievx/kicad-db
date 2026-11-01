"""Parametric candidates for passives from jlcsearch.tscircuit.com.

The source lists up to 100 parts per query, sorted by stock, but carries no
manufacturer name; the brand comes from the JLC record (jlc.lookup).
"""

from __future__ import annotations

import urllib.parse
from dataclasses import dataclass

from . import net
from .net import NetError

BASE_URL = "https://jlcsearch.tscircuit.com"
VALUE_MATCH = 0.005  # candidates further than 0.5 % from the requested value are dropped


@dataclass
class Candidate:
    lcsc: str
    mpn: str
    package: str
    value: float
    tolerance: float | None  # fraction, e.g. 0.01
    voltage: float | None  # V
    power_mw: float | None
    dielectric: str | None
    stock: int
    jlc_type: str  # "Basic" | "Preferred" | "Extended"


def _num(v: float) -> str:
    if v >= 1 and abs(v - round(v)) < 1e-9:
        return str(int(round(v)))
    return format(v, "g")


def _float(v) -> float | None:
    return None if v is None else float(v)


def _candidate(r: dict, value_key: str, kind: str) -> Candidate:
    try:
        jlc_type = "Preferred" if r.get("is_preferred") else "Basic" if r.get("is_basic") else "Extended"
        return Candidate(
            lcsc=f"C{int(r['lcsc'])}",
            mpn=str(r["mfr"]),
            package=str(r["package"]),
            value=float(r[value_key]),
            tolerance=_float(r.get("tolerance_fraction")),
            voltage=_float(r.get("voltage_rating")) if kind == "capacitors" else None,
            # The field is called power_watts but holds milliwatts.
            power_mw=_float(r.get("power_watts")) if kind == "resistors" else None,
            dielectric=(r.get("temperature_coefficient") or None) if kind == "capacitors" else None,
            stock=int(r.get("stock") or 0),
            jlc_type=jlc_type,
        )
    except (KeyError, TypeError, ValueError) as e:
        raise NetError(f"jlcsearch {kind}: unexpected record format ({e!r})") from e


def _list(kind: str, value_key: str, query_key: str, package: str, value: float, get) -> list[Candidate]:
    get = get or net.get_json
    url = f"{BASE_URL}/{kind}/list.json?" + urllib.parse.urlencode({"package": package, query_key: _num(value)})
    data = get(url)
    rows = data.get(kind) if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise NetError(f"{url}: expected a '{kind}' list")
    out = []
    for r in rows:
        if not isinstance(r, dict) or value_key not in r:
            raise NetError(f"{url}: record without {value_key}")
        if r[value_key] is None:
            continue
        c = _candidate(r, value_key, kind)
        if abs(c.value - value) <= VALUE_MATCH * value:
            out.append(c)
    return out


def resistors(package: str, ohms: float, get=None) -> list[Candidate]:
    return _list("resistors", "resistance", "resistance", package, ohms, get)


def capacitors(package: str, farads: float, get=None) -> list[Candidate]:
    return _list("capacitors", "capacitance_farads", "capacitance", package, farads, get)

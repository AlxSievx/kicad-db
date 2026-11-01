"""Candidates for one passive value (`libkit find`), for single adds.

Unlike bulk-add's picker this lists every usable part instead of choosing:
the hard limits (tolerance, voltage, dielectric, package, value, stock > 0)
filter, the selection rules only order the list (Basic/Preferred first, then
stock), and notes say where a part falls short of the bulk rules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import jlc, jlcsearch
from .entries import KINDS, kind_of, passive_entry, part_value
from .jlc import JlcPart
from .parts import load_parts
from .pick import FORBIDDEN_DIELECTRICS
from .schema import load_schema
from .values import format_value

BULK_MIN_STOCK = 1000  # rule 2 for bulk-added passives; below it a single add gets a note
DEFAULT_DIELECTRICS = ("C0G", "NP0", "X7R", "X5R")


@dataclass
class Option:
    part: JlcPart
    entry: dict | None
    notes: list[str] = field(default_factory=list)


def _rank(jlc_type: str, stock: int | None) -> tuple:
    return (jlc_type == "Extended", stock is None, -(stock or 0))


def _rc_parts(kind, value, package, max_tolerance, min_voltage, dielectrics, limit, get, lookup):
    search = jlcsearch.resistors if kind == "resistor" else jlcsearch.capacitors
    allowed = {d.upper() for d in dielectrics}
    pool = []
    for c in search(package, value, get=get):
        if max_tolerance is not None and (c.tolerance is None or c.tolerance > max_tolerance + 1e-12):
            continue
        if kind == "capacitor":
            if min_voltage is not None and (c.voltage is None or c.voltage < min_voltage):
                continue
            if c.dielectric is None or c.dielectric.upper() not in allowed:
                continue
        if c.stock == 0:
            continue
        pool.append(c)
    pool.sort(key=lambda c: _rank(c.jlc_type, c.stock))
    parts = []
    for c in pool:
        if len(parts) >= limit:
            break
        part = (lookup or jlc.lookup)(c.lcsc)
        if part is not None and part.stock > 0:
            parts.append(part)
    return parts


def _search_parts(kind, value, package, post):
    unit = KINDS[kind][2]
    text = format_value(value, unit)
    keyword = f"{text} {package}" if kind == "inductor" else f"{text[:-1] if text.endswith('R') else text}Ω {package}"
    out = []
    for part in jlc.search(keyword, post=post):
        if part.package != package or part.stock <= 0 or kind_of(part) != kind:
            continue
        v = part_value(kind, part)
        if v is not None and abs(v - value) <= jlcsearch.VALUE_MATCH * value:
            out.append(part)
    return out


def find(root: Path, kind: str, value: float, package: str, *, max_tolerance: float | None = None,
         min_voltage: float | None = None, dielectrics: tuple[str, ...] = DEFAULT_DIELECTRICS,
         limit: int = 10, get=None, post=None, lookup=None) -> list[Option]:
    if kind not in KINDS:
        raise ValueError(f"find supports {', '.join(KINDS)}, not {kind!r}")
    bad = [d for d in dielectrics if d.upper() in FORBIDDEN_DIELECTRICS]
    if bad:
        raise ValueError(f"dielectric {', '.join(bad)} is never allowed (rule 4)")
    root = Path(root)
    schema = load_schema(root)
    library = load_parts(root, schema)
    by_lcsc = {p.data.get("lcsc"): p.name for p in library if p.data.get("lcsc")}
    names = {p.name for p in library}

    if kind in ("resistor", "capacitor"):
        parts = _rc_parts(kind, value, package, max_tolerance, min_voltage, dielectrics, limit, get, lookup)
    else:
        parts = _search_parts(kind, value, package, post)
    parts.sort(key=lambda p: _rank(p.jlc_type, p.stock))

    out = []
    for part in parts[:limit]:
        notes = []
        if part.jlc_type == "Extended":
            notes.append("Extended")
        if part.stock < BULK_MIN_STOCK:
            notes.append(f"stock < {BULK_MIN_STOCK}")
        if schema.canonical_manufacturer(part.brand) is None:
            notes.append(f"unknown manufacturer {part.brand}")
        try:
            entry = passive_entry(kind, part, schema, known_only=False)
        except ValueError as e:
            entry = None
            notes.append(str(e))
        if part.lcsc in by_lcsc:
            notes.append(f"in library as {by_lcsc[part.lcsc]}")
        elif entry is not None and entry["name"] in names:
            notes.append(f"name {entry['name']} already in library")
        out.append(Option(part, entry, notes))
    return out

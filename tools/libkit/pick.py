"""Rule-based part picks for passives (spec §6.6).

1. Basic/Preferred before Extended.  2. Stock >= min_stock.
3. Known manufacturers only.  4. Ceramic dielectrics C0G/NP0, X7R, X5R only.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import jlc
from .jlc import JlcPart
from .jlcsearch import Candidate
from .schema import Schema

MAX_LOOKUPS = 8


@dataclass
class Need:
    kind: str  # "resistor" | "capacitor"
    value: float
    package: str
    max_tolerance: float
    min_voltage: float | None = None
    dielectrics: tuple[str, ...] = ("C0G", "NP0", "X7R", "X5R")
    min_stock: int = 1000


@dataclass
class Pick:
    need: Need
    part: JlcPart | None
    candidate: Candidate | None
    note: str


def _pct(f: float) -> str:
    return f"{f * 100:g}%"


def _filters(need: Need):
    yield (f"no candidate with tolerance ≤ {_pct(need.max_tolerance)}",
           lambda c: c.tolerance is not None and c.tolerance <= need.max_tolerance + 1e-12)
    if need.kind == "capacitor":
        if need.min_voltage is not None:
            yield (f"no candidate with voltage ≥ {need.min_voltage:g}V",
                   lambda c: c.voltage is not None and c.voltage >= need.min_voltage)
        allowed = {d.upper() for d in need.dielectrics}
        yield (f"no candidate with dielectric {'/'.join(need.dielectrics)}",
               lambda c: c.dielectric is not None and c.dielectric.upper() in allowed)
    yield f"no candidate with stock ≥ {need.min_stock}", lambda c: c.stock >= need.min_stock


def pick(need: Need, candidates: list[Candidate], schema: Schema, lookup=None) -> Pick:
    lookup = lookup or jlc.lookup
    if not candidates:
        return Pick(need, None, None, "no candidates at JLC")
    pool = list(candidates)
    for reason, keep in _filters(need):
        pool = [c for c in pool if keep(c)]
        if not pool:
            return Pick(need, None, None, reason)
    pool.sort(key=lambda c: (c.jlc_type == "Extended", -c.stock))

    checked = unknown = low = missing = 0
    for c in pool[:MAX_LOOKUPS]:
        checked += 1
        part = lookup(c.lcsc)
        if part is None:
            missing += 1
            continue
        if schema.canonical_manufacturer(part.brand) is None:
            unknown += 1
            continue
        if part.stock < need.min_stock:
            low += 1
            continue
        return Pick(need, part, c, "Extended part" if part.jlc_type == "Extended" else "")
    if unknown == checked:
        return Pick(need, None, None, f"no known manufacturer among {checked} checked")
    why = ", ".join(f"{n} {what}" for n, what in ((unknown, "unknown manufacturer"),
                                                    (low, f"stock < {need.min_stock} at JLC"),
                                                    (missing, "not found at JLC")) if n)
    return Pick(need, None, None, f"no usable part among {checked} checked ({why})")

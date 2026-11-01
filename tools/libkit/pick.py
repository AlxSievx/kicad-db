"""Rule-based part picks for passives (spec §6.6).

1. Basic/Preferred before Extended.  2. Stock >= min_stock.
3. Known manufacturers only.  4. Ceramic dielectrics C0G/NP0, X7R, X5R only.
6. Within the same JLC tier (Basic/Preferred, or Extended), a part with an
   English datasheet before one without (preference only, never a reason to
   pick nothing; see datasheet.py).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from . import jlc
from .datasheet import Result
from .jlc import JlcPart
from .jlcsearch import Candidate
from .schema import Schema

MAX_LOOKUPS = 8
MAX_LANG_CHECKS = 4  # datasheets examined per pick before settling for the best so far
LANG_RANK = {"en": 0, "unknown": 1, "zh": 2}
FORBIDDEN_DIELECTRICS = {"Y5V", "Z5U"}  # rule 4: never


@dataclass
class Need:
    kind: str  # "resistor" | "capacitor"
    value: float
    package: str
    max_tolerance: float
    min_voltage: float | None = None
    dielectrics: tuple[str, ...] = ("C0G", "NP0", "X7R", "X5R")
    min_stock: int = 1000

    def __post_init__(self):
        bad = [d.upper() for d in self.dielectrics if d.upper() in FORBIDDEN_DIELECTRICS]
        if bad:
            raise ValueError(f"dielectric {', '.join(bad)} is never allowed (rule 4: C0G/NP0, X7R or X5R)")


@dataclass
class Pick:
    need: Need
    part: JlcPart | None
    candidate: Candidate | None
    note: str
    datasheet: Result | None = None  # set when picked with a language check


def _chosen(need: Need, part: JlcPart, cand: Candidate, ds: Result | None) -> Pick:
    notes = []
    if part.jlc_type == "Extended":
        notes.append("Extended part")
    if ds is not None and ds.lang == "zh":
        notes.append("no English datasheet")
    elif ds is not None and ds.lang == "unknown":
        notes.append(f"datasheet language unknown ({ds.note})" if ds.note else "datasheet language unknown")
    return Pick(need, part, cand, "; ".join(notes), ds)


def _pct(f: float) -> str:
    return f"{f * 100:g}%"


def _filters(need: Need):
    yield (f"no candidate with tolerance ≤ {_pct(need.max_tolerance)}",
           lambda c: c.tolerance is not None and 0 <= c.tolerance <= need.max_tolerance + 1e-12)
    if need.kind == "capacitor":
        if need.min_voltage is not None:
            yield (f"no candidate with voltage ≥ {need.min_voltage:g}V",
                   lambda c: c.voltage is not None and c.voltage >= need.min_voltage)
        allowed = {d.upper() for d in need.dielectrics}
        yield (f"no candidate with dielectric {'/'.join(need.dielectrics)}",
               lambda c: c.dielectric is not None and c.dielectric.upper() in allowed)
    # Unknown stock passes: every pick is re-checked against JLC's own stock below.
    yield f"no candidate with stock ≥ {need.min_stock}", lambda c: c.stock is None or c.stock >= need.min_stock


def pick(need: Need, candidates: list[Candidate], schema: Schema, lookup=None,
         check: Callable[[JlcPart], str | None] | None = None,
         lang: Callable[[JlcPart], Result] | None = None) -> Pick:
    """The best candidate by the rules. `check` may reject a looked-up part
    (returning the reason); the walk then moves on to the next candidate.
    `lang` (datasheet language of a part) enables rule 6: without it the
    first usable part wins; with it, usable parts of the best JLC tier are
    compared until one has an English datasheet (at most MAX_LANG_CHECKS)."""
    lookup = lookup or jlc.lookup
    if not candidates:
        return Pick(need, None, None, "no candidates at JLC")
    pool = list(candidates)
    for reason, keep in _filters(need):
        pool = [c for c in pool if keep(c)]
        if not pool:
            return Pick(need, None, None, reason)
    pool.sort(key=lambda c: (c.jlc_type == "Extended", c.stock is None, -(c.stock or 0)))

    checked = unknown = low = missing = 0
    rejected: list[str] = []
    best = None  # ((tier, language rank), part, candidate, datasheet result)
    lang_checks = 0
    for c in pool[:MAX_LOOKUPS]:
        if best is not None and best[0][0] == 0 and c.jlc_type == "Extended":
            break  # only Extended candidates left, and a Basic/Preferred part is in hand
        if lang_checks >= MAX_LANG_CHECKS:
            break
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
        reason = check(part) if check else None
        if reason:
            rejected.append(reason)
            continue
        if lang is None:
            return _chosen(need, part, c, None)
        tier = int(part.jlc_type == "Extended")
        if best is not None and tier > best[0][0]:
            continue  # JLC's record says Extended although jlcsearch did not
        ds = lang(part)
        lang_checks += 1
        key = (tier, LANG_RANK.get(ds.lang, LANG_RANK["unknown"]))
        if best is None or key < best[0]:
            best = (key, part, c, ds)
        if key == (0, 0):
            break  # Basic/Preferred with an English datasheet: nothing better to find
    if best is not None:
        return _chosen(need, *best[1:])
    if unknown == checked:
        return Pick(need, None, None, f"no known manufacturer among {checked} checked")
    why = ", ".join(f"{n} {what}" for n, what in ((unknown, "unknown manufacturer"),
                                                    (low, f"stock < {need.min_stock} at JLC"),
                                                    (missing, "not found at JLC")) if n)
    if rejected:
        why = ", ".join(x for x in (why, "; ".join(dict.fromkeys(rejected[:3]))) if x)
    return Pick(need, None, None, f"no usable part among {checked} checked ({why})")

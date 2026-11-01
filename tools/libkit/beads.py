"""Chip ferrite beads and chip inductors for bulk add (plan 7).

jlcsearch has no parametric data for them, so candidates come from JLC's
keyword search ("600Ω 0603", "10uH 0805"), filtered by kind, package and value.
"""

from __future__ import annotations

import re

from .entries import kind_of, part_value
from .jlc import JlcPart
from .values import format_value

BEAD_FREQUENCY = "100MHz"
_CURRENT = re.compile(r"\s*(\d+(?:\.\d+)?)\s*(m?)A\s*")


def current_amps(text: str) -> float | None:
    """2A, 2000mA, 800mA -> amps; None for "-" or anything else."""
    m = _CURRENT.fullmatch(text or "")
    if not m:
        return None
    return float(m.group(1)) / (1000 if m.group(2) else 1)


def keyword(kind: str, value: float, package: str) -> str:
    if kind == "bead":
        text = format_value(value, "Ω")
        # JLC's search finds beads by "120Ω@100MHz", not by "120Ω" alone.
        return f"{text[:-1] if text.endswith('R') else text}Ω@{BEAD_FREQUENCY} {package}"
    return f"{format_value(value, 'H')} {package}"


def candidates(kind: str, value: float, package: str, search=None) -> list[JlcPart]:
    """JLC records of this kind, chip package and value (within 1%), any brand or stock."""
    from .jlc import search as jlc_search
    search = search or jlc_search
    found: dict[str, JlcPart] = {}
    for p in search(keyword(kind, value, package), pages=2):
        if p.package != package or kind_of(p) != kind:
            continue
        v = part_value(kind, p)
        if v is not None and abs(v - value) <= 0.01 * value:
            found.setdefault(p.lcsc, p)
    return list(found.values())

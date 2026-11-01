"""Tantalum and SMD aluminium electrolytic capacitors: case and can sizes.

JLC names one tantalum case in several ways ("CASE-A-3216-18(mm)", or the
imperial "1206" some makers use); an electrolytic can is "SMD,D6.3xL7.7mm",
with heights that vary a little per maker. Both map to one LIB footprint
(KiCad stock), so a value lands on the same part whatever the spelling.
"""

from __future__ import annotations

import re

from .jlc import JlcPart

TANTALUM_TYPE = "Tantalum Capacitors"
ELECTROLYTIC_TYPE = "Aluminum Electrolytic Capacitors - SMD"

# case letter: (EIA metric size, KiCad stock footprint)
CASES = {
    "A": ("3216-18", "CP_EIA-3216-18_Kemet-A"),
    "B": ("3528-21", "CP_EIA-3528-21_Kemet-B"),
    "C": ("6032-28", "CP_EIA-6032-28_Kemet-C"),
    "D": ("7343-31", "CP_EIA-7343-31_Kemet-D"),
}
IMPERIAL_CASE = {"1206": "A", "1411": "B", "2312": "C", "2917": "D"}
# can "<diameter>x<height>": KiCad stock footprint
CANS = {
    "5x5.4": "CP_Elec_5x5.4",
    "6.3x5.4": "CP_Elec_6.3x5.4",
    "6.3x7.7": "CP_Elec_6.3x7.7",
    "8x10.5": "CP_Elec_8x10.5",
    "10x10.5": "CP_Elec_10x10.5",
}
CAN_HEIGHT_TOLERANCE = 0.5  # mm: 6.3x5.3 … 6.3x5.8 are one can family, as are 8x10 and 8x10.5

_CASE = re.compile(r"CASE-([A-Z])-(\d{4}-\d{2})\(mm\)")
_CAN = re.compile(r"SMD,D(\d+(?:\.\d+)?)xL(\d+(?:\.\d+)?)mm")


def case_of(part: JlcPart) -> str | None:
    """The tantalum case letter (A–D) of a JLC record, or None."""
    if part.type_name != TANTALUM_TYPE:
        return None
    m = _CASE.fullmatch(part.package.strip())
    if m:
        letter = m.group(1)
        return letter if letter in CASES and CASES[letter][0] == m.group(2) else None
    return IMPERIAL_CASE.get(part.package.strip())


def can_of(part: JlcPart) -> str | None:
    """The electrolytic can key in CANS of a JLC record, or None."""
    if part.type_name != ELECTROLYTIC_TYPE:
        return None
    m = _CAN.fullmatch(part.package.strip().replace(" ", ""))
    if not m:
        return None
    d, l = float(m.group(1)), float(m.group(2))
    best = None
    for key in CANS:
        kd, kl = (float(x) for x in key.split("x"))
        if kd == d and abs(kl - l) <= CAN_HEIGHT_TOLERANCE + 1e-9:
            if best is None or abs(kl - l) < best[0]:
                best = (abs(kl - l), key)
    return best[1] if best else None


def size_of(kind: str, part: JlcPart) -> str | None:
    return case_of(part) if kind == "tantalum" else can_of(part)


def package_name(kind: str, size: str) -> str:
    """The LIB package text: CaseA, D6.3x7.7."""
    return f"Case{size}" if kind == "tantalum" else f"D{size}"


def footprint_name(kind: str, size: str) -> str:
    return CASES[size][1] if kind == "tantalum" else CANS[size]

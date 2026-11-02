"""Standard EIA E-series values (IEC 60063)."""

from __future__ import annotations

import math

# Mantissas as integers: E6–E24 at 2 significant digits, E48/E96 at 3.
_E24 = [10, 11, 12, 13, 15, 16, 18, 20, 22, 24, 27, 30, 33, 36, 39, 43, 47, 51, 56, 62, 68, 75, 82, 91]
_E96 = [100, 102, 105, 107, 110, 113, 115, 118, 121, 124, 127, 130, 133, 137, 140, 143, 147, 150, 154, 158,
        162, 165, 169, 174, 178, 182, 187, 191, 196, 200, 205, 210, 215, 221, 226, 232, 237, 243, 249, 255,
        261, 267, 274, 280, 287, 294, 301, 309, 316, 324, 332, 340, 348, 357, 365, 374, 383, 392, 402, 412,
        422, 432, 442, 453, 464, 475, 487, 499, 511, 523, 536, 549, 562, 576, 590, 604, 619, 634, 649, 665,
        681, 698, 715, 732, 750, 768, 787, 806, 825, 845, 866, 887, 909, 931, 953, 976]
SERIES = {
    "E6": (_E24[::4], 1),
    "E12": (_E24[::2], 1),
    "E24": (_E24, 1),
    "E48": (_E96[::2], 2),
    "E96": (_E96, 2),
}


# Fixed lists that are not E-series: ferrite-bead impedances in ohms at 100 MHz (plan 7).
FIXED = {"FB": [30.0, 60.0, 120.0, 220.0, 330.0, 470.0, 600.0, 1000.0, 1500.0, 2200.0]}


def values(name: str, start: float, stop: float) -> list[float]:
    """All values of series `name` in [start, stop], ascending."""
    if name in FIXED:
        return [v for v in FIXED[name] if start * (1 - 1e-9) <= v <= stop * (1 + 1e-9)]
    if name not in SERIES:
        raise ValueError(f"unknown series {name!r}; known: {', '.join([*SERIES, *FIXED])}")
    if not 0 < start <= stop:
        raise ValueError(f"bad range {start:g} .. {stop:g}")
    mantissas, shift = SERIES[name]
    lo, hi = start * (1 - 1e-9), stop * (1 + 1e-9)
    out = []
    for decade in range(math.floor(math.log10(start)) - 1, math.ceil(math.log10(stop)) + 1):
        for m in mantissas:
            v = float(f"{m}e{decade - shift}")  # from text: 47e2 is exactly 4700.0
            if lo <= v <= hi:
                out.append(v)
    return out


# Value codes of MPN series for `bulk-add discrete` (plan 8): BZT52C{} with "3V3" is BZT52C3V3.
MPN_VALUES = {
    "zener": ("2V4 2V7 3V0 3V3 3V6 3V9 4V3 4V7 5V1 5V6 6V2 6V8 7V5 8V2 9V1 10 11 12 13 15 16 18 20 22 24 27 30 "
              "33 36 39 43 47 51").split(),
    "tvs": ("5.0 6.0 6.5 7.0 7.5 8.0 8.5 9.0 10 11 12 13 14 15 16 17 18 20 22 24 26 28 30 33 36 40 43 45 48 51 54 "
            "58 60 64 70 75 78 85 90 100").split(),
}


def mpn_values(spec: str) -> list[str]:
    """A named list of MPN_VALUES, or a comma list of value codes ("14,16,110")."""
    if spec in MPN_VALUES:
        return list(MPN_VALUES[spec])
    out = [v.strip() for v in spec.split(",") if v.strip()]
    if not out:
        raise ValueError(f"--values: one of {', '.join(MPN_VALUES)} or a comma list, not {spec!r}")
    return out

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


def values(name: str, start: float, stop: float) -> list[float]:
    """All values of series `name` in [start, stop], ascending."""
    if name not in SERIES:
        raise ValueError(f"unknown series {name!r}; known: {', '.join(SERIES)}")
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

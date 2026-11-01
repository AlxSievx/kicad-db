"""Component value notation: parsing, canonical form and search spellings.

Canonical stored notation:
  resistors   10mR, 100R, 1.5R, 4.7k, 1M (unit "Ω")
  capacitors  10pF, 100nF, 4.7uF        (unit "F")
  inductors   10uH                      (unit "H")
"""

from __future__ import annotations

import re

_PREFIX = {"p": 1e-12, "n": 1e-9, "u": 1e-6, "µ": 1e-6, "m": 1e-3, "": 1.0, "R": 1.0,
           "k": 1e3, "M": 1e6, "G": 1e9}
# Prefixes used when formatting, smallest first.
_FORMAT_PREFIXES = {
    "F": ["p", "n", "u", "m", ""],
    "H": ["n", "u", "m", ""],
    "Ω": ["m", "", "k", "M", "G"],
}
_ALLOWED = {
    "F": set("pnuµm") | {""},
    "H": set("nuµm") | {""},
    "Ω": set("mkMGR") | {""},
}
_DEC = re.compile(r"(\d+(?:\.\d+)?)([pnuµmkMGR]?)")
_RKM = re.compile(r"(\d+)([pnuµmkMGR])(\d+)")


def _check_unit(unit: str) -> None:
    if unit not in _FORMAT_PREFIXES:
        raise ValueError(f"unknown unit {unit!r}")


def parse_value(text: str, unit: str) -> float:
    _check_unit(unit)
    s = text.strip()
    if s.endswith(unit):
        s = s[: -len(unit)]
    if unit == "Ω" and len(s) > 2 and s.endswith("R") and s[-2] in "mkMG":
        s = s[:-1]  # "10mR" (milliohm notation) and the like
    m = _DEC.fullmatch(s)
    if m:
        num, pre = m.group(1), m.group(2)
    else:
        m = _RKM.fullmatch(s)
        if not m:
            raise ValueError(f"cannot parse {text!r} as a value in {unit}")
        num, pre = f"{m.group(1)}.{m.group(3)}", m.group(2)
    if pre not in _ALLOWED[unit]:
        raise ValueError(f"prefix {pre!r} not allowed for unit {unit} in {text!r}")
    return float(num) * _PREFIX[pre]


def _mantissa(v: float, unit: str) -> tuple[str, str]:
    """Return (mantissa text, prefix) with mantissa in [1, 1000) where possible."""
    prefixes = _FORMAT_PREFIXES[unit]
    chosen = prefixes[0]
    if v != 0:
        for p in prefixes:
            if abs(v) / _PREFIX[p] >= 1 - 1e-9:
                chosen = p
    else:
        chosen = ""
    m = round(v / _PREFIX[chosen], 6)
    return f"{m:g}", chosen


def format_value(v: float, unit: str) -> str:
    _check_unit(unit)
    mant, pre = _mantissa(v, unit)
    if unit == "Ω":
        # Below 1R the "m" carries an "R" so 10mR can never be read as 10M.
        return f"{mant}R" if pre == "" else f"{mant}mR" if pre == "m" else f"{mant}{pre}"
    return f"{mant}{pre}{unit}"


def spellings(v: float, unit: str) -> list[str]:
    """Canonical form first, then alternative spellings for search."""
    _check_unit(unit)
    canonical = format_value(v, unit)
    mant, pre = _mantissa(v, unit)
    out = [canonical]
    if unit in ("F", "H"):
        out.append(canonical[: -len(unit)])
    if "." in mant:
        whole, frac = mant.split(".")
        out.append(f"{whole}{pre or 'R'}{frac}")
    if unit in ("F", "H") and float(mant) >= 100:
        idx = _FORMAT_PREFIXES[unit].index(pre)
        if idx + 1 < len(_FORMAT_PREFIXES[unit]):
            nxt = _FORMAT_PREFIXES[unit][idx + 1]
            out.append(f"{round(float(mant) / 1000, 6):g}{nxt}{unit}")
    if unit in ("F", "H"):
        out += [s.replace("u", "µ") for s in list(out) if s.endswith(unit) and "u" in s]
    else:
        out.append(canonical[:-1] + "Ω" if canonical.endswith("R") else canonical + "Ω")
    return list(dict.fromkeys(out))

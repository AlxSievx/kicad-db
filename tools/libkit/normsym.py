"""Normalise an imported symbol (KiCad 10 format) to the library style (spec §6.5).

Input is a symbol as `kicad-cli sym upgrade` writes it from easyeda2kicad
output: renamed to the part, the standard fields only, 1.27 mm text, a
0.254 mm outline, pins on the 100 mil grid, and pin types where the pin name
makes them clear. What a machine cannot decide comes back as notes.
"""

from __future__ import annotations

import copy
import math
import re

from .sexpr import Sym, find, find_all
from .symgen import STANDARD, _hidden_prop

GRID = 2.54
OUTLINE_WIDTH = "0.254"
FONT_SIZE = "1.27"
PIN_TYPES = {"input", "output", "bidirectional", "tri_state", "passive", "free", "unspecified",
             "power_in", "power_out", "open_collector", "open_emitter", "no_connect"}
PIN_RULES = [  # pin name -> type, for pins still "unspecified"
    (re.compile(r"(GND|[AP]GND|VSS|EP)\d*", re.I), "power_in"),
    # Exact supply names (plus a number) only: VINP/VINN/VOUTP are signals.
    (re.compile(r"(VCC|VDD|VIN|VBAT|V\+|AVDD|DVDD|VDDA|VDDIO|VCCIO)\d*", re.I), "power_in"),
    (re.compile(r"VOUT\d*", re.I), "power_out"),
    (re.compile(r"(NC|DNC)", re.I), "no_connect"),
]
POINT_HEADS = ("at", "start", "mid", "end", "center", "xy")
OUTLINES = ("rectangle", "polyline", "circle", "arc", "bezier")


def _num(v: float) -> Sym:
    text = f"{round(v, 4):.4f}".rstrip("0").rstrip(".")
    return Sym("0" if text in ("-0", "") else text)


def _is(node, *heads) -> bool:
    return isinstance(node, list) and bool(node) and str(node[0]) in heads


def rename_symbol(sym: list, name: str) -> list:
    """`sym` renamed to `name`, including its unit sub-symbols <old>_<unit>_<style>."""
    sym = copy.deepcopy(sym)
    old = str(sym[1])
    sym[1] = name
    for unit in find_all(sym, "symbol"):
        u = str(unit[1])
        if u.startswith(old + "_"):
            unit[1] = name + u[len(old):]
    return sym


def clean_properties(sym: list) -> None:
    """Only the standard fields, in the fixed order; values empty except the
    Reference prefix (build fills in the rest from the YAML)."""
    have = {str(p[1]): p for p in find_all(sym, "property")}
    new = []
    for name in STANDARD:
        node = have.get(name) or _hidden_prop(name, "")
        if name != "Reference":
            node[2] = ""
        new.append(node)
    first = next((i for i, c in enumerate(sym) if _is(c, "property")), None)
    rest = [c for c in sym if not _is(c, "property")]
    if first is None:
        first = next((i for i, c in enumerate(rest) if _is(c, "symbol")), len(rest))
    sym[:] = rest[:first] + new + rest[first:]


def _walk(node: list, fn) -> None:
    for c in node:
        if isinstance(c, list) and c:
            fn(c)
            _walk(c, fn)


def _translate(node: list, dx: float, dy: float) -> None:
    def move(c):
        if str(c[0]) in POINT_HEADS and len(c) >= 3:
            c[1], c[2] = _num(float(c[1]) + dx), _num(float(c[2]) + dy)
    _walk(node, move)


def _pins(sym: list) -> list[list]:
    return [p for u in find_all(sym, "symbol") for p in find_all(u, "pin")]


def _offset(v: float) -> float:
    """Distance above the grid line below v, in [0, GRID); ~GRID counts as 0."""
    off = v - math.floor(v / GRID + 1e-9) * GRID
    return 0.0 if off < 1e-3 or GRID - off < 1e-3 else off


def _pin_label(pin: list) -> str:
    return f"{find(pin, 'name')[1]}(#{find(pin, 'number')[1]})"


def normalize_symbol(sym: list, name: str, pin_types: dict[str, str] | None = None) -> tuple[list, list[str]]:
    sym = rename_symbol(sym, name)
    notes: list[str] = []
    clean_properties(sym)

    def style(c):
        head = str(c[0])
        if head == "font":
            size = find(c, "size")
            if size is not None:
                size[1:] = [Sym(FONT_SIZE), Sym(FONT_SIZE)]
        elif head in OUTLINES:
            stroke = find(c, "stroke")
            width = find(stroke, "width") if stroke else None
            if width is not None and float(width[1]) == 0:
                width[1] = Sym(OUTLINE_WIDTH)
    _walk(sym, style)

    # Pins on the 100 mil grid: shift everything when all pins share one offset.
    pins = _pins(sym)
    offs = {(round(_offset(float(find(p, "at")[1])), 3), round(_offset(float(find(p, "at")[2])), 3)) for p in pins}
    if len(offs) == 1 and offs != {(0.0, 0.0)}:
        ox, oy = next(iter(offs))
        dx = -ox if ox <= GRID / 2 else GRID - ox
        dy = -oy if oy <= GRID / 2 else GRID - oy
        _translate(sym, dx, dy)
        notes.append(f"moved onto the 100 mil grid by ({_num(dx)}, {_num(dy)}) mm")
    elif len(offs) > 1:
        off = [_pin_label(p) for p in pins
               if (_offset(float(find(p, "at")[1])), _offset(float(find(p, "at")[2]))) != (0.0, 0.0)]
        notes.append(f"pins off the 100 mil grid: {', '.join(off)}")

    # Pin types: given ones first, then from the pin name.
    for key, kind in (pin_types or {}).items():
        if kind not in PIN_TYPES:
            raise ValueError(f"unknown pin type {kind!r}; one of {', '.join(sorted(PIN_TYPES))}")
        hits = [p for p in pins if (key.startswith("#") and str(find(p, "number")[1]) == key[1:])
                or str(find(p, "name")[1]) == key]
        if not hits:
            raise ValueError(f"no pin named {key!r} (use the name, or #<number>)")
        for p in hits:
            p[1] = Sym(kind)
    unknown = []
    for p in pins:
        if str(p[1]) != "unspecified":
            continue
        pin_name = str(find(p, "name")[1])
        kind = next((k for rx, k in PIN_RULES if rx.fullmatch(pin_name)), None)
        if kind:
            p[1] = Sym(kind)
        else:
            unknown.append(_pin_label(p))
    if unknown:
        notes.append(f"pin types unknown: {', '.join(unknown)} — pass --pin-types")
    return sym, notes

"""Bulk add of resistors and capacitors by value series (spec §6.7).

plan() decides per value: an existing part already covers it ("exists"), a
new pick by the selection rules ("new"), or no usable part ("none"). It never
writes. apply() writes all new rows in one category rewrite, then builds.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from . import jlcsearch, series
from .entries import KINDS, passive_entry
from .parts import Part, load_parts, validate, write_category
from .pick import Need, pick
from .schema import load_schema
from .values import format_value, parse_value


@dataclass
class Row:
    value: str
    name: str
    status: str  # "new" | "exists" | "none"
    entry: dict | None
    note: str


def _num(text: str, pattern: str) -> float | None:
    m = re.fullmatch(pattern, text.strip())
    return float(m.group(1)) if m else None


def _mismatch(d: dict, value: float, unit: str, need: Need) -> str | None:
    """Why part data `d` does not satisfy the need, or None when it does."""
    if d.get("package") != need.package:
        return f"package {d.get('package')}"
    try:
        v = parse_value(d.get("value", ""), unit)
    except ValueError:
        return f"value {d.get('value')!r}"
    if abs(v - value) > jlcsearch.VALUE_MATCH * value:
        return f"value {d.get('value')}"
    tol = _num(d.get("tolerance", ""), r"±?\s*(\d+(?:\.\d+)?)\s*%")
    if tol is None or tol / 100 > need.max_tolerance + 1e-12:
        return f"tolerance {d.get('tolerance')}"
    if need.kind == "capacitor":
        volts = _num(d.get("voltage", ""), r"(\d+(?:\.\d+)?)\s*V")
        if need.min_voltage is not None and (volts is None or volts < need.min_voltage):
            return f"voltage {d.get('voltage')}"
        if d.get("dielectric", "").upper() not in {x.upper() for x in need.dielectrics}:
            return f"dielectric {d.get('dielectric')}"
    return None


def _fits(p: Part, value: float, unit: str, need: Need) -> bool:
    """An active library part that already satisfies the need."""
    return p.data.get("status") == "active" and _mismatch(p.data, value, unit, need) is None


def plan(root: Path, kind: str, series_name: str, start: float, stop: float, package: str,
         max_tolerance: float, min_voltage: float | None, dielectrics: tuple[str, ...],
         get=None, lookup=None) -> list[Row]:
    root = Path(root)
    if kind not in KINDS:
        raise ValueError(f"bulk-add supports {', '.join(KINDS)}, not {kind!r}")
    category, _, unit, _ = KINDS[kind]
    schema = load_schema(root)
    library = load_parts(root, schema)
    existing = [p for p in library if p.category == category]
    names = {p.name: p for p in library}
    by_lcsc = {p.data["lcsc"]: p for p in names.values() if p.data.get("lcsc")}
    search = jlcsearch.resistors if kind == "resistor" else jlcsearch.capacitors

    rows: list[Row] = []
    for v in series.values(series_name, start, stop):
        text = format_value(v, unit)
        need = Need(kind, v, package, max_tolerance, min_voltage if kind == "capacitor" else None,
                    **({"dielectrics": tuple(dielectrics)} if kind == "capacitor" else {}))
        have = next((p for p in existing if _fits(p, v, unit, need)), None)
        if have is not None:
            rows.append(Row(text, have.name, "exists", have.data, "already in library"))
            continue
        built: dict[str, dict] = {}

        def check(part, need=need, v=v, built=built):
            # The entry is built from JLC's own record; it must still meet the
            # request (jlcsearch's figures can be stale or incomplete).
            try:
                e = passive_entry(kind, part, schema)
            except ValueError as ex:
                return str(ex)
            why = _mismatch(e, v, unit, need)
            if why:
                return f"{part.lcsc}: {why} at JLC"
            built[part.lcsc] = e
            return None

        result = pick(need, search(package, v, get=get), schema, lookup=lookup, check=check)
        if result.part is None:
            rows.append(Row(text, "", "none", None, result.note))
            continue
        entry = built[result.part.lcsc]
        if entry["name"] in names:
            old = names[entry["name"]]
            rows.append(Row(text, entry["name"], "exists", old.data,
                            f"name already in library ({old.data.get('status', '?')}, {old.data.get('lcsc', '-')})"))
        elif entry["lcsc"] in by_lcsc:
            old = by_lcsc[entry["lcsc"]]
            rows.append(Row(text, entry["name"], "exists", old.data,
                            f"{entry['lcsc']} already in library as {old.name}"))
        else:
            rows.append(Row(text, entry["name"], "new", entry, result.note))
    return rows


def apply(root: Path, kind: str, rows: list[Row]) -> int:
    """Write every "new" row into parts/<category>.yaml in one rewrite, then build."""
    from .build import build
    root = Path(root)
    new = [r.entry for r in rows if r.status == "new"]
    if not new:
        return 0
    category = KINDS[kind][0]
    schema = load_schema(root)
    library = load_parts(root, schema)
    added = [Part(e["name"], category, e, root / "parts" / f"{category}.yaml") for e in new]
    bad = [i for i in validate(library + added, schema) if i.severity == "error"]
    if bad:
        raise ValueError("refusing to write invalid parts: " + "; ".join(str(i) for i in bad))
    write_category(root, category, [p.data for p in library if p.category == category] + new)
    build(root)
    return len(new)

"""Stock refresh: re-query every part at JLC (spec §6.7).

All lookups happen first; any NetError aborts before a single file is written.
Only stock, stock_checked and jlc_type are updated. Everything worth a human
look is returned as a Change.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from . import jlc
from .parts import load_parts, write_category
from .schema import load_schema

LOW_STOCK_PASSIVE = 1000  # categories with a value unit (bulk-picked passives)
LOW_STOCK_OTHER = 100


@dataclass
class Change:
    part: str
    kind: str  # "not_found" | "out_of_stock" | "low_stock" | "type_changed" | "mpn_changed"
    detail: str

    def __str__(self) -> str:
        return f"{self.kind:<13} {self.part}: {self.detail}"


def refresh(root: Path, lookup=None, today: date | None = None) -> list[Change]:
    lookup = lookup or jlc.lookup
    root = Path(root)
    schema = load_schema(root)
    parts = load_parts(root, schema)
    stamp = (today or date.today()).isoformat()

    found = {p.name: lookup(p.data["lcsc"]) for p in parts if p.data.get("lcsc")}

    changes: list[Change] = []
    touched: set[str] = set()
    for p in parts:
        if p.name not in found:
            continue
        lcsc, rec = p.data["lcsc"], found[p.name]
        if rec is None:
            changes.append(Change(p.name, "not_found", f"{lcsc} is no longer listed at JLC"))
            continue
        old = dict(p.data)
        if rec.mpn != p.data.get("mpn"):
            changes.append(Change(p.name, "mpn_changed", f"{lcsc}: library {p.data.get('mpn')!r}, JLC {rec.mpn!r}"))
        if rec.jlc_type != p.data.get("jlc_type"):
            changes.append(Change(p.name, "type_changed", f"{lcsc}: {p.data.get('jlc_type')} → {rec.jlc_type}"))
            p.data["jlc_type"] = rec.jlc_type
        threshold = LOW_STOCK_PASSIVE if schema.categories[p.category].value_unit else LOW_STOCK_OTHER
        if rec.stock == 0:
            changes.append(Change(p.name, "out_of_stock", f"{lcsc}: 0 in stock"))
        elif rec.stock < threshold:
            changes.append(Change(p.name, "low_stock", f"{lcsc}: {rec.stock} in stock (< {threshold})"))
        p.data["stock"] = str(rec.stock)
        p.data["stock_checked"] = stamp
        if p.data != old:
            touched.add(p.category)

    for category in sorted(touched):
        write_category(root, category, [p.data for p in parts if p.category == category])
    return changes

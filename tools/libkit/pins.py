"""Symbol pin numbers against footprint pad numbers (spec §6.8)."""

from __future__ import annotations

from pathlib import Path

from .parts import Issue, Part
from .sexpr import find, parse


def _pins(expr: list, acc: set[str]) -> set[str]:
    for c in expr:
        if isinstance(c, list) and c:
            if c[0] == "pin":
                num = find(c, "number")
                if num is not None and str(num[1]):
                    acc.add(str(num[1]))
            elif c[0] == "symbol":
                _pins(c, acc)
    return acc


def symbol_pins(name: str, sources: dict[str, list]) -> set[str]:
    """Pin numbers of source symbol `name` over all units, following `extends`."""
    sym = sources[name]
    seen = {name}
    while (ext := find(sym, "extends")) is not None:
        parent = str(ext[1])
        if parent in seen:
            raise ValueError(f"symbol {name!r}: extends loop at {parent!r}")
        seen.add(parent)
        sym = sources[parent]
    return _pins(sym, set())


def footprint_pads(path: Path) -> set[str]:
    """Non-empty pad numbers of a .kicad_mod file."""
    fp = parse(Path(path).read_text(encoding="utf-8"))
    return {str(c[1]) for c in fp if isinstance(c, list) and c and c[0] == "pad" and str(c[1])}


def _sorted(nums: set[str]) -> str:
    return ", ".join(sorted(nums, key=lambda n: (not n.isdigit(), int(n) if n.isdigit() else 0, n)))


def pin_pad_issues(parts: list[Part], sources: dict[str, list], root: Path) -> list[Issue]:
    """Per part whose symbol and footprint exist: an error for symbol pins
    without a pad, a warning for numbered pads without a pin."""
    pads_by_fp: dict[str, set[str]] = {}
    issues: list[Issue] = []
    for p in parts:
        sym, fp = p.data.get("symbol", ""), p.data.get("footprint", "")
        lib, _, name = fp.partition(":")
        path = Path(root) / "footprints" / f"{lib}.pretty" / f"{name}.kicad_mod"
        if sym not in sources or not name or not path.exists():
            continue
        if fp not in pads_by_fp:
            pads_by_fp[fp] = footprint_pads(path)
        pins, pads = symbol_pins(sym, sources), pads_by_fp[fp]
        if pins - pads:
            issues.append(Issue("error", p.name, f"symbol pin(s) {_sorted(pins - pads)} have no pad in {fp}"))
        if pads - pins:
            issues.append(Issue("warning", p.name, f"footprint pad(s) {_sorted(pads - pins)} of {fp} have no "
                                                   f"symbol pin"))
    return issues

"""Power-inductor families for bulk add (plan 7): one manufacturer series
(e.g. Sunlord SWPA4030S), one shared footprint, one part per inductance."""

from __future__ import annotations

import re
from pathlib import Path

from .entries import part_value
from .jlc import JlcPart

FAMILY_LIB = "LIB_Inductor_SMD"


def family_member(family: str, mpn: str) -> bool:
    """`mpn` is the family prefix, an optional "-", an inductance code (100,
    4R7, R47) and a short suffix (tolerance/packaging letters)."""
    rest = mpn.strip().upper()
    fam = family.strip().upper()
    if not rest.startswith(fam):
        return False
    code = r"(\d{3}|\d+R\d+|R\d+|\d+(?:\.\d+)?[UM]H)"  # 100, 4R7, R47, or a spelled value: 47UH
    return re.fullmatch(rf"-?{code}[A-Z]{{0,3}}", rest[len(fam):]) is not None


def family_footprint(root: Path, family: str) -> str | None:
    """The footprint parts of this family use: from a family part already in
    the library, else LIB_Inductor_SMD:L_<brand>_<family> when that file exists."""
    from .parts import load_parts
    from .schema import load_schema
    root = Path(root)
    for p in load_parts(root, load_schema(root)):
        if p.category == "inductors" and family_member(family, p.data.get("mpn", "")):
            return p.data["footprint"]
    for f in sorted((root / "footprints" / f"{FAMILY_LIB}.pretty").glob(f"L_*_{family}.kicad_mod")):
        return f"{FAMILY_LIB}:{f.stem}"
    return None


def candidates(family: str, value: float, search=None) -> list[JlcPart]:
    from .jlc import search as jlc_search
    search = search or jlc_search
    found: dict[str, JlcPart] = {}
    for p in search(family, pages=3):
        if not family_member(family, p.mpn):
            continue
        v = part_value("inductor", p)
        if v is not None and abs(v - value) <= 0.01 * value:
            found.setdefault(p.lcsc, p)
    return list(found.values())

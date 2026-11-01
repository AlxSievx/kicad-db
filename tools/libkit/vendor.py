"""Copy symbols, footprints and 3D models from KiCad's stock library into LIB."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from .schema import Family
from .sexpr import Sym, dumps, find, find_all, parse
from .symgen import SYM_VERSION, write_text

_MODEL = re.compile(r'\(model\s+"\$\{KICAD\d+_3DMODEL_DIR\}/([^"/]+)\.3dshapes/([^"]+)"')


def _split(ref: str) -> tuple[str, str]:
    lib, sep, name = ref.partition(":")
    if not sep or not lib or not name:
        raise ValueError(f"expected <library>:<name>, got {ref!r}")
    return lib, name


def vendor_footprint(stock_ref: str, family: Family, root: Path, kicad_share: Path) -> Path:
    lib, name = _split(stock_ref)
    src = Path(kicad_share) / "footprints" / f"{lib}.pretty" / f"{name}.kicad_mod"
    if not src.exists():
        raise FileNotFoundError(src)
    text = src.read_text(encoding="utf-8")
    models_dir = Path(root) / "3dmodels" / f"{family.lib_name}.3dshapes"
    copies: list[tuple[Path, Path]] = []

    def rewrite(m: re.Match) -> str:
        model_src = Path(kicad_share) / "3dmodels" / f"{m.group(1)}.3dshapes" / m.group(2)
        if not model_src.exists():
            raise FileNotFoundError(model_src)
        copies.append((model_src, models_dir / m.group(2)))
        return f'(model "${{LIB_DIR}}/3dmodels/{family.lib_name}.3dshapes/{m.group(2)}"'

    text = _MODEL.sub(rewrite, text)
    for a, b in copies:
        b.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(a, b)
    dest = Path(root) / "footprints" / f"{family.lib_name}.pretty" / f"{name}.kicad_mod"
    write_text(dest, text)
    return dest


def vendor_symbol(stock_ref: str, dest: Path, kicad_share: Path) -> None:
    lib, name = _split(stock_ref)
    src_file = Path(kicad_share) / "symbols" / f"{lib}.kicad_sym"
    stock = {str(s[1]): s for s in find_all(parse(src_file.read_text(encoding="utf-8")), "symbol")}
    if name not in stock:
        raise KeyError(f"{name!r} not in {src_file.name}")

    chain = [name]
    while (ext := find(stock[chain[-1]], "extends")) is not None:
        chain.append(str(ext[1]))

    dest = Path(dest)
    if dest.exists():
        lib_expr = parse(dest.read_text(encoding="utf-8"))
    else:
        lib_expr = [Sym("kicad_symbol_lib"), [Sym("version"), Sym(SYM_VERSION)],
                    [Sym("generator"), "libkit"], [Sym("generator_version"), "1.0"]]
    present = {str(s[1]) for s in find_all(lib_expr, "symbol")}
    for n in reversed(chain):  # parent first
        if n not in present:
            lib_expr.append(stock[n])
            present.add(n)
    write_text(dest, dumps(lib_expr))

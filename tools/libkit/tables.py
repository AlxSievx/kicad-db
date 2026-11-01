"""KiCad library tables (nested; every uri goes through ${LIB_DIR})."""

from __future__ import annotations

from pathlib import Path

from .schema import Schema
from .sexpr import Sym, dumps

TABLE_VERSION = "7"


def _lib(name: str, uri: str, descr: str) -> list:
    return [Sym("lib"), [Sym("name"), name], [Sym("type"), "KiCad"], [Sym("uri"), uri],
            [Sym("options"), ""], [Sym("descr"), descr]]


def sym_lib_table(schema: Schema) -> str:
    libs = [_lib(c.lib_name, f"${{LIB_DIR}}/symbols/{c.lib_name}.kicad_sym", c.title)
            for c in schema.categories.values()]
    return dumps([Sym("sym_lib_table"), [Sym("version"), Sym(TABLE_VERSION)], *libs])


def fp_lib_table(root: Path) -> str:
    libs = [_lib(d.stem, f"${{LIB_DIR}}/footprints/{d.name}", d.stem.removeprefix("LIB_").replace("_", " "))
            for d in sorted((Path(root) / "footprints").glob("*.pretty")) if d.is_dir()]
    return dumps([Sym("fp_lib_table"), [Sym("version"), Sym(TABLE_VERSION)], *libs])

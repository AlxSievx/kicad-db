"""Generate native KiCad symbol libraries from parts and source symbols."""

from __future__ import annotations

import copy
from pathlib import Path

from .parts import Part
from .schema import Category, Schema
from .sexpr import Sym, dumps, find, find_all, parse
from .text import build_description, build_keywords

SYM_VERSION = "20251024"
VISIBLE = {"Reference", "Value"}
STANDARD = ["Reference", "Value", "Footprint", "Datasheet", "Description"]


def write_text(path: Path, text: str) -> None:
    """UTF-8, LF line endings — regardless of platform defaults."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def load_source_symbols(root: Path) -> dict[str, list]:
    out: dict[str, list] = {}
    origin: dict[str, str] = {}
    for f in sorted((Path(root) / "src" / "symbols").glob("*.kicad_sym")):
        lib = parse(f.read_text(encoding="utf-8"))
        for s in find_all(lib, "symbol"):
            name = str(s[1])
            if name in out:
                raise ValueError(f"duplicate source symbol {name!r} in {f.name} and {origin[name]}")
            out[name] = s
            origin[name] = f.name
    return out


def _hidden_prop(name: str, value: str, at: list | None = None) -> list:
    return [Sym("property"), name, value,
            at or [Sym("at"), Sym("0"), Sym("0"), Sym("0")],
            [Sym("show_name"), Sym("no")],
            [Sym("do_not_autoplace"), Sym("no")],
            [Sym("hide"), Sym("yes")],
            [Sym("effects"), [Sym("font"), [Sym("size"), Sym("1.27"), Sym("1.27")]]]]


def _set_hidden(node: list, hide: bool) -> list:
    node = [c for c in node if not (isinstance(c, list) and c and c[0] == "hide")]
    if hide:
        eff = next((i for i, c in enumerate(node) if isinstance(c, list) and c[0] == "effects"), len(node))
        node.insert(eff, [Sym("hide"), Sym("yes")])
    return node


def _properties(part: Part, src: list, schema: Schema, unique: bool) -> list[list]:
    """Property nodes for one part, in the fixed order."""
    cat = schema.categories[part.category]
    base_props = {str(p[1]): p for p in find_all(src, "property")}
    values = {
        "Reference": str(base_props["Reference"][2]) if "Reference" in base_props else "U",
        "Value": part.data.get("value", ""),
        "Footprint": part.data.get("footprint", ""),
        "Datasheet": part.data.get("datasheet", ""),
        "Description": build_description(part, schema),
    }
    out = []
    for name in STANDARD:
        if name in base_props:
            node = copy.deepcopy(base_props[name])
            node[2] = values[name]
            out.append(_set_hidden(node, name not in VISIBLE))
        else:
            out.append(_hidden_prop(name, values[name]))
    for f in schema.fields_for(cat):
        if f.label and part.data.get(f.key):
            out.append(_hidden_prop(f.label, part.data[f.key]))
    out.append(_hidden_prop("ki_keywords", build_keywords(part, schema)))
    if unique and "ki_fp_filters" in base_props:
        out.append(copy.deepcopy(base_props["ki_fp_filters"]))
    return out


def _derived(part: Part, base: list, schema: Schema) -> list:
    return [Sym("symbol"), part.name, [Sym("extends"), str(base[1])],
            *_properties(part, base, schema, unique=False),
            [Sym("embedded_fonts"), Sym("no")]]


def _unique(part: Part, src: list, schema: Schema) -> list:
    props = _properties(part, src, schema, unique=True)
    out, inserted = [], False
    for c in src:
        if isinstance(c, list) and c and c[0] == "property":
            if not inserted:
                out.extend(props)
                inserted = True
            continue
        out.append(copy.deepcopy(c))
    if not inserted:
        out[2:2] = props
    return out


def build_symbol_lib(category: Category, parts: list[Part], sources: dict[str, list],
                     schema: Schema) -> str:
    bases_used: set[str] = set()
    for p in parts:
        sym = p.data.get("symbol", "")
        if sym not in sources:
            raise ValueError(f"{p.name}: unknown symbol {sym!r}")
        if sym != p.name:
            bases_used.add(sym)
    for p in parts:
        if p.name in bases_used:
            raise ValueError(f"part name {p.name!r} collides with a base symbol used in {category.lib_name}")
        if p.name != p.data.get("symbol") and p.name in sources:
            raise ValueError(f"part name {p.name!r} collides with a base symbol in src/symbols")

    body: list = []
    for name in sorted(bases_used):
        body.append(copy.deepcopy(sources[name]))
    for p in sorted(parts, key=lambda p: p.name):
        src = sources[p.data["symbol"]]
        if p.data["symbol"] == p.name:
            body.append(_unique(p, src, schema))
        else:
            body.append(_derived(p, src, schema))
    lib = [Sym("kicad_symbol_lib"),
           [Sym("version"), Sym(SYM_VERSION)],
           [Sym("generator"), "libkit"],
           [Sym("generator_version"), "1.0"],
           *body]
    return dumps(lib)

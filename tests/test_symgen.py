import dataclasses
import subprocess

import pytest
from conftest import part

from libkit.kicad import find_kicad_cli
from libkit.parts import load_parts
from libkit.sexpr import find, find_all, parse
from libkit.symgen import build_symbol_lib, load_source_symbols

kicad = pytest.mark.skipif(find_kicad_cli() is None, reason="kicad-cli not found")


@pytest.fixture
def sources(minilib):
    return load_source_symbols(minilib)


@pytest.fixture
def cat(schema):
    return schema.categories["capacitors"]


@pytest.fixture
def cap(minilib):
    return part(minilib, "C_100n_0402_16V_X7R")


@pytest.fixture
def lib_text(cat, cap, sources, schema):
    return build_symbol_lib(cat, [cap], sources, schema)


def symbol(e, name):
    return next(s for s in find_all(e, "symbol") if s[1] == name)


def props(s):
    return [p[1] for p in find_all(s, "property")]


def prop(s, name):
    return next(p[2] for p in find_all(s, "property") if p[1] == name)


def hidden(s, name):
    p = next(p for p in find_all(s, "property") if p[1] == name)
    return find(p, "hide") == ["hide", "yes"]


def renamed(p, name, **data):
    return dataclasses.replace(p, name=name, data={**p.data, "name": name, **data})


def test_header(lib_text):
    e = parse(lib_text)
    assert e[0] == "kicad_symbol_lib"
    assert find(e, "version") == ["version", "20251024"]
    assert find(e, "generator") == ["generator", "libkit"]


def test_derived_symbol_properties(lib_text):
    s = symbol(parse(lib_text), "C_100n_0402_16V_X7R")
    assert find(s, "extends") == ["extends", "C"]
    assert props(s) == ["Reference", "Value", "Footprint", "Datasheet", "Description",
                        "Manufacturer", "MPN", "LCSC", "JLC_Type", "Voltage", "Dielectric",
                        "Tolerance", "ki_keywords"]
    assert prop(s, "Value") == "100nF"
    assert prop(s, "Footprint") == "LIB_Passives_SMD:C_0402_1005Metric"
    assert prop(s, "Description") == "100nF 16V X7R ±10% 0402 capacitor"
    assert prop(s, "ki_keywords").startswith("100nF 100n 0.1uF")
    assert hidden(s, "MPN") and hidden(s, "Footprint")
    assert not hidden(s, "Value") and not hidden(s, "Reference")


def test_stock_not_in_symbol(lib_text):
    assert "48200000" not in lib_text and "2026-10-30" not in lib_text


def test_base_emitted_once_and_first(cat, cap, sources, schema):
    other = renamed(cap, "C_1u_0402_10V_X5R", value="1uF")
    e = parse(build_symbol_lib(cat, [other, cap], sources, schema))
    names = [s[1] for s in find_all(e, "symbol")]
    assert names == ["C", "C_100n_0402_16V_X7R", "C_1u_0402_10V_X5R"]


def test_empty_category_is_valid_lib(cat, sources, schema):
    e = parse(build_symbol_lib(cat, [], sources, schema))
    assert find_all(e, "symbol") == []


def test_unique_symbol_gets_fields(cat, cap, sources, schema):
    # A part whose symbol is its own (name == symbol): emitted in full, properties replaced.
    sources = dict(sources)
    sources["MYPART"] = [*sources["C"][:1], "MYPART", *sources["C"][2:]]
    p = renamed(cap, "MYPART", symbol="MYPART")
    s = symbol(parse(build_symbol_lib(cat, [p], sources, schema)), "MYPART")
    assert find(s, "extends") is None
    assert prop(s, "MPN") == "CL05B104KO5NNNC"
    assert find(s, "property") is not None and len(find_all(s, "symbol")) == 2  # sub-units kept


def test_unicode_roundtrip(tmp_path, lib_text):  # Review Focus 2
    from libkit.symgen import write_text
    out = tmp_path / "x.kicad_sym"
    write_text(out, lib_text)
    raw = out.read_bytes()
    assert "±10%".encode("utf-8") in raw and b"\r\n" not in raw


def test_part_named_like_base_rejected(cat, cap, sources, schema):  # Review Focus 5
    clash = renamed(cap, "C", symbol="C")
    with pytest.raises(ValueError, match="base symbol"):
        build_symbol_lib(cat, [cap, clash], sources, schema)


def test_unknown_base_rejected(cat, cap, sources, schema):
    with pytest.raises(ValueError, match="unknown symbol"):
        build_symbol_lib(cat, [renamed(cap, "X1", symbol="NOPE")], sources, schema)


def test_duplicate_source_symbol_rejected(minilib):
    d = minilib / "src" / "symbols"
    (d / "copy.kicad_sym").write_text((d / "passives.kicad_sym").read_text(encoding="utf-8"), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        load_source_symbols(minilib)


def test_deterministic(cat, cap, sources, schema):
    assert build_symbol_lib(cat, [cap], sources, schema) == build_symbol_lib(cat, [cap], sources, schema)


@kicad
def test_kicad_cli_loads_generated_lib(tmp_path, minilib, cat, cap, sources, schema):
    from libkit.symgen import write_text
    tricky = renamed(cap, "C_10n_0402_50V_X7R", value="10nF", description='say "hi" back\\slash µ°')
    lib = tmp_path / "LIB_Capacitors.kicad_sym"
    write_text(lib, build_symbol_lib(cat, [cap, tricky], sources, schema))
    out = tmp_path / "svg"
    r = subprocess.run([str(find_kicad_cli()), "sym", "export", "svg", str(lib), "-o", str(out)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    names = [p.name.lower() for p in out.iterdir()]
    assert any(n.startswith("c_100n") for n in names), names
    assert any(n.startswith("c_10n") for n in names), names

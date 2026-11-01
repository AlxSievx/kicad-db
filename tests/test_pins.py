import re

from libkit.check import check
from libkit.parts import load_parts
from libkit.pins import footprint_pads, pin_pad_issues, symbol_pins
from libkit.schema import load_schema
from libkit.sexpr import parse
from libkit.symgen import load_source_symbols

FP = "footprints/LIB_Passives_SMD.pretty"


def _fp_with_pads(root, name, pads):
    src = (root / FP / "R_0402_1005Metric.kicad_mod").read_text(encoding="utf-8")
    first = src.index('\t(pad "1"')
    end = src.index("\n\t(", src.index('\t(pad "2"') + 1)
    body = "".join(f'\t(pad "{p}" smd roundrect (at {i} 0) (size 0.5 0.5) (layers "F.Cu"))\n'
                   for i, p in enumerate(pads))
    text = src[:first] + body + src[end + 1:]
    text = text.replace('(footprint "R_0402_1005Metric"', f'(footprint "{name}"')
    (root / FP / f"{name}.kicad_mod").write_text(text, encoding="utf-8")


def _use_footprint(root, name):
    f = root / "parts" / "resistors.yaml"
    text = f.read_text(encoding="utf-8")
    f.write_text(text.replace("LIB_Passives_SMD:R_0402_1005Metric", f"LIB_Passives_SMD:{name}", 1),
                 encoding="utf-8")


def _issues(root):
    s = load_schema(root)
    return pin_pad_issues(load_parts(root, s), load_source_symbols(root), root)


def test_symbol_pins_passive(minilib):
    assert symbol_pins("R", load_source_symbols(minilib)) == {"1", "2"}


def test_symbol_pins_follows_extends():
    base = parse('(symbol "Base" (symbol "Base_1_1" (pin passive line (at 0 0 0) (length 1)'
                 ' (name "~") (number "1")) (pin passive line (at 0 2 0) (length 1) (name "~") (number "2"))))')
    child = parse('(symbol "Child" (extends "Base"))')
    assert symbol_pins("Child", {"Base": base, "Child": child}) == {"1", "2"}


def test_footprint_pads_ignores_unnumbered(minilib):
    _fp_with_pads(minilib, "X3", ["1", "2", ""])
    assert footprint_pads(minilib / FP / "X3.kicad_mod") == {"1", "2"}


def test_pin_without_pad_is_error(minilib):
    _fp_with_pads(minilib, "X1", ["1"])
    _use_footprint(minilib, "X1")
    errs = [i for i in _issues(minilib) if i.severity == "error"]
    assert len(errs) == 1 and re.search(r"pin\(s\) 2 have no pad", errs[0].message)


def test_extra_pad_is_warning(minilib):
    _fp_with_pads(minilib, "X3", ["1", "2", "MP"])
    _use_footprint(minilib, "X3")
    issues = _issues(minilib)
    assert [i.severity for i in issues] == ["warning"] and "MP" in issues[0].message


def test_check_clean_on_minilib(minilib):
    assert not [i for i in check(minilib, klc=False) if "pin" in i.message]


def test_check_reports_pin_without_pad(minilib):
    _fp_with_pads(minilib, "X1", ["1"])
    _use_footprint(minilib, "X1")
    assert any("have no pad" in i.message for i in check(minilib, klc=False))

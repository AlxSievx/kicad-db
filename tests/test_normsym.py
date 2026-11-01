import shutil
from pathlib import Path

import pytest

from libkit.normsym import normalize_symbol, rename_symbol
from libkit.sexpr import find, find_all, parse
from libkit.symgen import STANDARD
from libkit.vendor import stock_symbol

FIX = Path(__file__).parent / "fixtures" / "easyeda"
AMS_LIB = FIX / "C6186" / "up" / "E2K.kicad_sym"


def lib_symbols(text: str) -> dict[str, list]:
    return {str(s[1]): s for s in find_all(parse(text), "symbol")}


def ams(text: str | None = None) -> list:
    return lib_symbols(text or AMS_LIB.read_text(encoding="utf-8"))["AMS1117-3.3"]


def pins(sym: list) -> dict[str, list]:
    return {str(find(p, "number")[1]): p for u in find_all(sym, "symbol") for p in find_all(u, "pin")}


def props(sym: list) -> dict[str, list]:
    return {str(p[1]): p for p in find_all(sym, "property")}


def find_all_deep(node, head):
    out = []
    for c in node:
        if isinstance(c, list) and c:
            if c[0] == head:
                out.append(c)
            out += find_all_deep(c, head)
    return out


def test_easyeda_symbol_rules():
    sym, notes = normalize_symbol(ams(), "AMS1117-3.3")
    assert list(props(sym)) == STANDARD
    assert str(props(sym)["Reference"][2]) == "U"  # build takes the reference prefix from here
    assert all(str(props(sym)[n][2]) == "" for n in STANDARD[1:])
    rect = find(find_all(sym, "symbol")[0], "rectangle")
    assert str(find(find(rect, "stroke"), "width")[1]) == "0.254"
    for p in pins(sym).values():
        at = find(p, "at")
        for v in (float(at[1]), float(at[2])):
            assert abs(v / 2.54 - round(v / 2.54)) < 1e-6
    types = {n: str(p[1]) for n, p in pins(sym).items()}
    assert types == {"1": "power_in", "2": "power_out", "3": "power_in", "4": "power_out"}
    assert not any("pin types unknown" in n for n in notes)


def test_grid_shift_keeps_body_and_pins_together():
    before = ams()
    sym, notes = normalize_symbol(before, "AMS1117-3.3")
    old_rect = find(find_all(before, "symbol")[0], "rectangle")
    new_rect = find(find_all(sym, "symbol")[0], "rectangle")
    dx = float(find(new_rect, "start")[1]) - float(find(old_rect, "start")[1])
    assert abs(abs(dx) - 1.27) < 1e-9
    assert float(find(pins(sym)["1"], "at")[1]) == pytest.approx(-11.43 + dx)
    assert any(n.startswith("moved onto the 100 mil grid") for n in notes)


def test_fonts_are_1_27():
    text = AMS_LIB.read_text(encoding="utf-8").replace("(size 1.27 1.27)", "(size 1 1)")
    sym, _ = normalize_symbol(ams(text), "AMS1117-3.3")
    sizes = [s for s in find_all_deep(sym, "size") if len(s) == 3]
    assert sizes and all([str(s[1]), str(s[2])] == ["1.27", "1.27"] for s in sizes)


def test_pin_types_override():
    sym, _ = normalize_symbol(ams(), "X", pin_types={"VIN": "input", "#4": "passive"})
    types = {n: str(p[1]) for n, p in pins(sym).items()}
    assert types["3"] == "input" and types["4"] == "passive" and types["2"] == "power_out"


def test_pin_types_bad_value():
    with pytest.raises(ValueError, match="pin type"):
        normalize_symbol(ams(), "X", pin_types={"VIN": "powr_in"})


def test_pin_types_unknown_pin():
    with pytest.raises(ValueError, match="no pin"):
        normalize_symbol(ams(), "X", pin_types={"EN": "input"})


def test_unknown_pin_types_noted():
    text = AMS_LIB.read_text(encoding="utf-8").replace('(name "GND"', '(name "EN"').replace('(name "VIN"', '(name "FB"')
    _, notes = normalize_symbol(ams(text), "X")
    note = next(n for n in notes if n.startswith("pin types unknown"))
    assert "EN(#1)" in note and "FB(#3)" in note


def test_mixed_grid_offsets_noted():
    text = AMS_LIB.read_text(encoding="utf-8").replace("(at -11.43 -2.54 0)", "(at -10.16 -2.54 0)")
    _, notes = normalize_symbol(ams(text), "X")
    assert any(n.startswith("pins off the 100 mil grid") for n in notes)


def test_rename_multi_unit():  # Review Focus 3
    s = rename_symbol(lib_symbols((FIX / "dual.kicad_sym").read_text(encoding="utf-8"))["OPA_X"], "LM358DR")
    assert s[1] == "LM358DR"
    assert [str(c[1]) for c in find_all(s, "symbol")] == ["LM358DR_0_1", "LM358DR_1_1", "LM358DR_2_1"]


@pytest.fixture
def tmp_share(tmp_path):
    (tmp_path / "symbols").mkdir()
    shutil.copy(FIX / "dual.kicad_sym", tmp_path / "symbols" / "Test.kicad_sym")
    return tmp_path


def test_flatten_stock_extends(tmp_share):  # Review Focus 3
    s = stock_symbol("Test:CHILD", tmp_share, "PART1")
    assert s[1] == "PART1" and find(s, "extends") is None
    assert [str(c[1]) for c in find_all(s, "symbol")] == ["PART1_0_1", "PART1_1_1", "PART1_2_1"]
    assert list(props(s)) == STANDARD
    assert str(props(s)["Reference"][2]) == "U" and str(props(s)["Description"][2]) == ""
    assert find(s, "pin_names") is not None


def test_flatten_two_levels(tmp_share):
    s = stock_symbol("Test:GRANDCHILD", tmp_share, "PART2")
    assert find(s, "extends") is None and str(props(s)["Reference"][2]) == "IC"
    assert len(find_all(s, "symbol")) == 3


def test_stock_symbol_unknown(tmp_share):
    with pytest.raises(KeyError):
        stock_symbol("Test:NOPE", tmp_share, "X")

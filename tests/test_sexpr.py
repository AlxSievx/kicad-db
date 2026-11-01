from pathlib import Path

import pytest

from libkit.sexpr import Sym, dumps, find, find_all, parse

DEVICE_LIB = Path(r"C:\Program Files\KiCad\10.0\share\kicad\symbols\Device.kicad_sym")


def test_parse_distinguishes_symbols_and_strings():
    e = parse('(property "Value" "C" (at 0.635 -2.54 0) (hide yes))')
    assert e[0] == "property" and isinstance(e[0], Sym)
    assert e[1] == "Value" and not isinstance(e[1], Sym)
    assert find(e, "at") == ["at", "0.635", "-2.54", "0"]
    assert isinstance(find(e, "at")[1], Sym)


def test_string_escaping():
    e = [Sym("property"), Sym("x"), 'a "quoted" \\ back\nline']
    text = dumps(e)
    assert parse(text) == e
    assert '\\"quoted\\"' in text
    assert "\\n" in text


def test_dumps_kicad_style():
    e = parse('(a "s" (b 1 2) (c (d x)))')
    assert dumps(e) == '(a "s"\n\t(b 1 2)\n\t(c\n\t\t(d x)\n\t)\n)\n'


def test_find_all_returns_only_direct_children():
    e = parse("(lib (symbol a (symbol a_0)) (symbol b) (other))")
    assert [s[1] for s in find_all(e, "symbol")] == ["a", "b"]
    assert find(e, "missing") is None


def test_parse_rejects_unbalanced():
    with pytest.raises(ValueError):
        parse("(a (b)")


@pytest.mark.skipif(not DEVICE_LIB.exists(), reason="KiCad 10 stock library not installed")
def test_roundtrip_stock_device_lib():
    e = parse(DEVICE_LIB.read_text(encoding="utf-8"))
    assert parse(dumps(e)) == e
    assert len(find_all(e, "symbol")) > 100

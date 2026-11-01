import shutil
from dataclasses import replace

import pytest

from conftest import FIXTURE
from fakes import fake_get, paged_fake
from libkit.find import find
from libkit.parts import load_parts, write_category
from libkit.schema import load_schema
from test_pick import make_lookup

TYPES = {"C25744": "Basic"}


def find_r(root, **kw):
    kw.setdefault("lookup", make_lookup(brand="YAGEO", types=TYPES))
    return find(root, "resistor", 10000, "0402", max_tolerance=0.01, get=fake_get("res_0402_10000.json"), **kw)


def test_find_resistor_orders_by_rules(minilib):
    opts = find_r(minilib)
    assert 0 < len(opts) <= 10
    assert opts[0].part.lcsc == "C25744" and opts[0].part.jlc_type == "Basic"
    rest = [o.part.stock for o in opts[1:]]
    assert rest == sorted(rest, reverse=True)
    assert all(o.entry is not None and o.entry["tolerance"] for o in opts[:1])


def test_find_respects_tolerance(minilib):
    # 5 % parts (C60489, C144731) never appear in a 1 % search.
    assert not {"C60489", "C144731"} & {o.part.lcsc for o in find_r(minilib, limit=20)}


def test_find_marks_existing(minilib):
    schema = load_schema(minilib)
    res = [p.data for p in load_parts(minilib, schema) if p.category == "resistors"]
    assert any(d.get("lcsc") == "C25744" for d in res)  # the fixture library has R_10k_0402_1pct
    opt = next(o for o in find_r(minilib) if o.part.lcsc == "C25744")
    assert "in library as R_10k_0402_1pct" in opt.notes


def test_find_keeps_low_stock_and_unknown_brand(minilib):
    # C25744 comes from a recorded JLC record, so its entry can be built.
    opts = find_r(minilib, lookup=make_lookup(brand="YAGEO", types=TYPES, brands={"C25744": "NoName"},
                                              stock={"C25744": 50}))
    opt = next(o for o in opts if o.part.lcsc == "C25744")
    assert "stock < 1000" in opt.notes
    assert "unknown manufacturer NoName" in opt.notes
    assert opt.entry["manufacturer"] == "NoName"


def test_find_drops_zero_stock(minilib):
    opts = find_r(minilib, lookup=make_lookup(brand="YAGEO", types=TYPES, stock={"C2906861": 0}))
    assert "C2906861" not in {o.part.lcsc for o in opts}


def test_find_inductor(minilib):
    opts = find(minilib, "inductor", 10e-6, "0805", post=paged_fake("search_10uH_0805.json"), limit=30)
    lcscs = [o.part.lcsc for o in opts]
    assert lcscs[0] == "C1046"  # the only Basic one
    assert "C27798" not in lcscs  # stock 0
    assert all(o.part.package == "0805" for o in opts)
    ext = [o.part.stock for o in opts[1:]]
    assert ext == sorted(ext, reverse=True)
    no_current = next(o for o in opts if o.part.lcsc == "C88182")
    assert no_current.entry is None and any("Current Rating" in n for n in no_current.notes)
    assert next(o for o in opts if o.part.lcsc == "C1046").entry["name"] == "L_10u_0805_15mA"


def test_find_inductor_value_filter(minilib):
    assert find(minilib, "inductor", 4.7e-6, "0805", post=paged_fake("search_10uH_0805.json")) == []


def test_find_unknown_kind(minilib):
    with pytest.raises(ValueError):
        find(minilib, "diode", 1, "0805")


def test_cli_find_prints_table(minilib, monkeypatch, capsys):
    from libkit import __main__ as cli, net
    monkeypatch.chdir(minilib)
    monkeypatch.setattr(net, "post_json", paged_fake("search_10uH_0805.json"))
    assert cli.main(["find", "inductor", "10u", "--package", "0805"]) == 0
    out = capsys.readouterr().out
    assert out.splitlines()[0].startswith("LCSC") and "L_10u_0805_15mA" in out

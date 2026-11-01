"""Plan 7: bulk add of chip ferrite beads, chip inductors and power-inductor families."""

import shutil
from dataclasses import replace

import pytest

from conftest import REPO
from fakes import rec
from libkit.beads import current_amps
from libkit.bulk import apply, load_plan, plan, save_plan
from libkit.check import check
from libkit.families import family_footprint, family_member
from libkit.jlc import parse_record
from libkit.pick import pick_ranked
from libkit.schema import load_schema


def part(code):
    return parse_record(rec(code))


def variant(code, **kw):
    p = part(code)
    attrs = dict(p.attributes)
    for k in list(kw):
        if k in ("Impedance @ Frequency", "Current Rating", "Inductance"):
            attrs[k] = kw.pop(k)
    return replace(p, attributes=attrs, **kw)


@pytest.fixture
def schema():
    return load_schema(REPO)


def test_current_amps():  # Review Focus 2
    assert current_amps("2A") == 2 and current_amps("2000mA") == 2 and current_amps("800mA") == 0.8
    assert current_amps("-") is None and current_amps("") is None


def test_bead_frequency_must_be_100mhz(schema):  # Review Focus 1
    at1m = variant("C1015", lcsc="C930", **{"Impedance @ Frequency": "100Ω@1MHz"})
    p = pick_ranked("bead", 100.0, "0805", [at1m], schema)
    assert p.part is None and "100MHz" in p.note


def test_bead_current_order(schema):  # Review Focus 2
    basic = variant("C1015", lcsc="C931", jlc_type="Basic", **{"Current Rating": "200mA"})
    ext2a = variant("C1015", lcsc="C932", jlc_type="Extended", **{"Current Rating": "2A"})
    ext2000 = variant("C1015", lcsc="C933", jlc_type="Extended", stock=5000, **{"Current Rating": "2000mA"})
    nocur = variant("C1015", lcsc="C934", jlc_type="Basic", **{"Current Rating": "-"})
    assert pick_ranked("bead", 100.0, "0805", [ext2a, basic, nocur], schema).part.lcsc == "C931"
    assert pick_ranked("bead", 100.0, "0805", [ext2000, ext2a], schema).part.lcsc == "C932"  # same 2 A: more stock
    p = pick_ranked("bead", 100.0, "0805", [nocur], schema)
    assert p.part is None and "C934" in p.note


def fake_search(by_keyword_start):
    def search(keyword, pages=2, post=None):
        return by_keyword_start.get(keyword.split()[0], [])
    return search


RUN_FB = dict(kind="bead", series_name="FB", start=60.0, stop=120.0, package="0805",
              max_tolerance=1.0, min_voltage=None, dielectrics=(), min_power=None)


def lib(minilib):
    shutil.copy(REPO / "src" / "symbols" / "passives.kicad_sym", minilib / "src" / "symbols" / "passives.kicad_sym")
    for f in ("L_0805_2012Metric",):
        shutil.copy(REPO / "footprints" / "LIB_Passives_SMD.pretty" / f"{f}.kicad_mod",
                    minilib / "footprints" / "LIB_Passives_SMD.pretty")
        shutil.copy(REPO / "3dmodels" / "LIB_Passives_SMD.3dshapes" / f"{f}.step",
                    minilib / "3dmodels" / "LIB_Passives_SMD.3dshapes")
    return minilib


def test_plan_bead_rows(minilib):
    root = lib(minilib)
    rows = plan(root, **RUN_FB, search=fake_search({"100Ω@100MHz": [part("C1015")]}))
    assert [(r.value, r.status) for r in rows] == [("60R@100MHz", "none"), ("120R@100MHz", "none")]
    rows = plan(root, **{**RUN_FB, "start": 100.0, "stop": 100.0, "series_name": "E6"},
                search=fake_search({"100Ω@100MHz": [part("C1015")]}))
    assert rows[0].status == "new" and rows[0].name == "FB_100R_0805_800mA"


def test_fb_series_values():
    from libkit.series import values
    assert values("FB", 30, 2200) == [30, 60, 120, 220, 330, 470, 600, 1000, 1500, 2200]


def test_write_bead_plan(minilib):
    root = lib(minilib)
    run = {**RUN_FB, "start": 100.0, "stop": 100.0, "series_name": "E6"}
    rows = plan(root, **run, search=fake_search({"100Ω@100MHz": [part("C1015")]}))
    save_plan(root, run, rows)
    back, _ = load_plan(root, run)
    assert apply(root, "bead", back) == 1
    assert [i for i in check(root, klc=False) if i.severity == "error"] == []


def test_plan_chip_inductor(minilib):
    root = lib(minilib)
    run = dict(kind="inductor", series_name="E6", start=1e-5, stop=1e-5, package="0805",
               max_tolerance=1.0, min_voltage=None, dielectrics=(), min_power=None)
    rows = plan(root, **run, search=fake_search({"10uH": [part("C1046")]}))
    assert rows[0].status == "new" and rows[0].name == "L_10u_0805_15mA"


# ---- power-inductor families ---------------------------------------------------------------------
def test_family_prefix_exact():  # Review Focus 3
    assert family_member("MWSA0503S", "MWSA0503S-100MT") and family_member("SWPA4030S", "SWPA4030S100MT")
    assert family_member("SWPA4030S", "SWPA4030S4R7MT") and family_member("SWPA4030S", "SWPA4030SR47NT")
    assert not family_member("SWPA4030S", "SWPA40301S100MT") and not family_member("SWPA4030S", "SWPA4030T100MT")


def test_family_requires_footprint(minilib):  # Review Focus 4
    run = dict(kind="inductor", series_name="E6", start=1e-5, stop=1e-5, package="MWSA0503S",
               max_tolerance=1.0, min_voltage=None, dielectrics=(), min_power=None, family=True)
    with pytest.raises(ValueError, match="libkit add"):
        plan(lib(minilib), **run, search=fake_search({"MWSA0503S": [part("C408412")]}))


def _with_family_fp(root):
    d = root / "footprints" / "LIB_Inductor_SMD.pretty"
    d.mkdir(parents=True, exist_ok=True)
    src = (REPO / "footprints" / "LIB_Passives_SMD.pretty" / "L_0805_2012Metric.kicad_mod").read_text(encoding="utf-8")
    (d / "L_Sunlord_MWSA0503S.kicad_mod").write_text(
        src.replace('"L_0805_2012Metric"', '"L_Sunlord_MWSA0503S"').replace(
            "${LIB_DIR}/3dmodels/LIB_Passives_SMD.3dshapes/L_0805_2012Metric.step",
            "${LIB_DIR}/3dmodels/LIB_Passives_SMD.3dshapes/L_0805_2012Metric.step"), encoding="utf-8")
    from libkit.parts import declare_family
    declare_family(root, "Inductor_SMD")
    return root


def test_family_one_row_per_value(minilib):  # Review Focus 5
    root = _with_family_fp(lib(minilib))
    a = part("C408412")
    b = replace(a, lcsc="C408413", mpn="MWSA0503S-100NT", stock=900_000)
    c = replace(a, lcsc="C408414", mpn="MWSA0503S-100KT", jlc_type="Basic", stock=2000)
    run = dict(kind="inductor", series_name="E6", start=1e-5, stop=1e-5, package="MWSA0503S",
               max_tolerance=1.0, min_voltage=None, dielectrics=(), min_power=None, family=True)
    rows = plan(root, **run, search=fake_search({"MWSA0503S": [a, b, c]}))
    assert len(rows) == 1 and rows[0].entry["lcsc"] == "C408414"  # Basic first


def test_family_entry(minilib):
    root = _with_family_fp(lib(minilib))
    assert family_footprint(root, "MWSA0503S") == "LIB_Inductor_SMD:L_Sunlord_MWSA0503S"
    run = dict(kind="inductor", series_name="E6", start=1e-5, stop=1e-5, package="MWSA0503S",
               max_tolerance=1.0, min_voltage=None, dielectrics=(), min_power=None, family=True)
    rows = plan(root, **run, search=fake_search({"MWSA0503S": [part("C408412")]}))
    e = rows[0].entry
    assert e["name"] == "MWSA0503S-100MT" and e["value"] == "10uH" and e["footprint"].endswith("L_Sunlord_MWSA0503S")
    assert e["current_rating"] == "3.2A" and e["current_sat"] == "3.5A" and e["dcr"] == "125mΩ"
    save_plan(root, run, rows)
    back, _ = load_plan(root, run)
    assert apply(root, "inductor", back) == 1
    assert [i for i in check(root, klc=False) if i.severity == "error"] == []


def test_cli_bead_needs_package(minilib, monkeypatch, capsys):
    from libkit import __main__ as cli
    monkeypatch.chdir(minilib)
    assert cli.main(["bulk-add", "bead", "--series", "FB", "--from", "30", "--to", "2200"]) == 1
    assert "0402" in capsys.readouterr().err
    assert cli.main(["bulk-add", "inductor", "--series", "E6", "--from", "1u", "--to", "10u",
                     "--family", "NOPE1234"]) == 1
    assert "libkit add" in capsys.readouterr().err


def test_skip_bead_rows():  # final review I1
    from libkit.bulk import Row, skip_rows
    rows = [Row("600R@100MHz", "FB_600R_0603_200mA", "new", {}, ""), Row("1k@100MHz", "FB_1k_0603_200mA", "new", {}, "")]
    out = skip_rows(rows, ["1k"], "Ω")
    assert [r.status for r in out] == ["new", "skipped"]
    assert [r.status for r in skip_rows(rows, ["600R@100MHz"], "Ω")] == ["skipped", "new"]


def test_bead_keyword_has_frequency():  # live: "120Ω 0603" finds no beads at JLC, "120Ω@100MHz 0603" does
    from libkit.beads import keyword
    assert keyword("bead", 120.0, "0603") == "120Ω@100MHz 0603"
    assert keyword("bead", 1000.0, "0402") == "1kΩ@100MHz 0402"
    assert keyword("inductor", 1e-5, "0805") == "10uH 0805"


def test_bead_write_keeps_inductor_plan_valid(minilib):  # deferred minor 3: kinds share the inductors category
    root = lib(minilib)
    run_l = dict(kind="inductor", series_name="E6", start=1e-5, stop=1e-5, package="0805",
                 max_tolerance=1.0, min_voltage=None, dielectrics=(), min_power=None, family=False)
    save_plan(root, run_l, plan(root, **run_l, search=fake_search({"10uH": [part("C1046")]})))
    run_b = {**RUN_FB, "start": 100.0, "stop": 100.0, "series_name": "E6"}
    rows = plan(root, **run_b, search=fake_search({"100Ω@100MHz": [part("C1015")]}))
    apply(root, "bead", rows)
    load_plan(root, run_l)  # must not say "changed since the last dry run"


def test_common_mode_filter_is_not_a_bead():  # 4-pin chokes are single adds with a coupled-inductor symbol
    from libkit.entries import kind_of
    p = replace(part("C1015"), type_name="Common Mode Filters", package="SMD-4P,3.2x2.5mm")
    assert kind_of(p) is None


def test_family_member_value_codes():
    assert family_member("CY75-", "CY75-47UH") and family_member("CY75-", "CY75-100UH")
    assert family_member("YPRH1209", "YPRH1209-101M")
    assert not family_member("CY75-", "CY75-47UHXYZQ")

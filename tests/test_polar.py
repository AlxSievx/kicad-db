import shutil

import pytest

from conftest import REPO
from fakes import rec
from libkit.build import build
from libkit.check import check
from libkit.entries import kind_of, passive_entry
from libkit.jlc import parse_record
from libkit.parts import write_category
from libkit.polar import can_of, case_of
from libkit.schema import load_schema


def part(code):
    return parse_record(rec(code))


@pytest.fixture
def schema():
    return load_schema(REPO)


def test_case_and_can_mapping():  # plan 6 Review Focus 2
    assert case_of(part("C7171")) == "A" and case_of(part("C16133")) == "B" and case_of(part("C122293")) == "C"
    assert case_of(part("C6328904")) == "A"  # tantalum labelled "1206"
    assert case_of(part("C1525")) is None  # a real 0402 MLCC
    assert can_of(part("C125975")) == "6.3x7.7" and can_of(part("C88736")) == "8x10.5"
    assert can_of(part("C128532")) == "6.3x5.4"  # D6.3xL5.8 is the same can family
    assert can_of(part("C7171")) is None and can_of(part("C454283")) is None  # tantalum; hybrid polymer


def test_kind_of_polar():
    assert kind_of(part("C7171")) == "tantalum" and kind_of(part("C6328904")) == "tantalum"
    assert kind_of(part("C125975")) == "electrolytic"
    assert kind_of(part("C454283")) is None  # hybrid: not a plain electrolytic
    assert kind_of(part("C1525")) == "capacitor"


def test_tantalum_entry(schema):
    e = passive_entry("tantalum", part("C7171"), schema)
    assert e["name"] == "C_10u_CaseA_16V_Ta" and e["symbol"] == "C_Polarized"
    assert e["manufacturer"] == "KYOCERA AVX" and e["package"] == "CaseA"
    assert e["footprint"] == "LIB_Passives_SMD:CP_EIA-3216-18_Kemet-A"
    assert (e["value"], e["voltage"], e["dielectric"], e["tolerance"]) == ("10uF", "16V", "Ta", "±10%")
    assert e["esr"] == "3Ω@100kHz"


def test_electrolytic_entry(schema):
    e = passive_entry("electrolytic", part("C125975"), schema)
    assert e["name"] == "C_100u_D6.3x7.7_35V_Al" and e["manufacturer"] == "Nichicon"
    assert e["footprint"] == "LIB_Passives_SMD:CP_Elec_6.3x7.7" and e["package"] == "D6.3x7.7"
    assert e["lifetime"] == "1000hrs@105°C" and "esr" not in e


def test_unknown_brand_without_prefix_stays_unknown(schema):
    assert schema.canonical_manufacturer("--", "XYZ123") is None
    assert schema.canonical_manufacturer("--", "TAJA106K016RNJ") == "KYOCERA AVX"
    assert schema.canonical_manufacturer("Wurth Elektronik") == "Würth Elektronik"


def test_polarized_pins_match_pads(minilib, schema):  # plan 6 Review Focus 3
    for f in ("CP_EIA-3216-18_Kemet-A", "CP_Elec_6.3x7.7"):
        shutil.copy(REPO / "footprints" / "LIB_Passives_SMD.pretty" / f"{f}.kicad_mod",
                    minilib / "footprints" / "LIB_Passives_SMD.pretty")
        for m in (REPO / "3dmodels" / "LIB_Passives_SMD.3dshapes").glob(f"{f}.*"):
            shutil.copy(m, minilib / "3dmodels" / "LIB_Passives_SMD.3dshapes")
    shutil.copy(REPO / "src" / "symbols" / "passives.kicad_sym", minilib / "src" / "symbols" / "passives.kicad_sym")
    from libkit.parts import load_parts
    caps = [p.data for p in load_parts(minilib, load_schema(minilib)) if p.category == "capacitors"]
    write_category(minilib, "capacitors", caps + [passive_entry("tantalum", part("C7171"), schema),
                                                  passive_entry("electrolytic", part("C125975"), schema)])
    build(minilib)
    assert [str(i) for i in check(minilib, klc=False) if "pin" in i.message or i.severity == "error"] == []


# ---- Task 4: bulk add -----------------------------------------------------------------------------
from dataclasses import replace  # noqa: E402

from libkit.bulk import apply, load_plan, plan, save_plan  # noqa: E402
from libkit.datasheet import Result  # noqa: E402
from libkit.pick import pick_polar  # noqa: E402


def variant(code, **kw):
    p = part(code)
    attrs = dict(p.attributes)
    for k in ("Voltage Rating", "Capacitance"):
        if k in kw:
            attrs[k] = kw.pop(k)
    return replace(p, attributes=attrs, **kw)


def test_voltage_order_within_tier(schema):  # plan 6 Review Focus 5
    basic16 = variant("C7171", lcsc="C901", jlc_type="Basic")
    ext35 = variant("C7171", lcsc="C902", jlc_type="Extended", **{"Voltage Rating": "35V"})
    ext16 = variant("C7171", lcsc="C903", jlc_type="Extended")
    assert pick_polar("tantalum", 1e-5, "A", [ext35, basic16], schema).part.lcsc == "C901"
    assert pick_polar("tantalum", 1e-5, "A", [ext16, ext35], schema).part.lcsc == "C902"


def test_odd_records_rejected(schema):  # plan 6 Review Focus 4
    bad_v = variant("C7171", lcsc="C904", jlc_type="Basic", **{"Voltage Rating": "-"})
    bad_c = variant("C7171", lcsc="C905", jlc_type="Basic", **{"Capacitance": "10uF±20%"})
    good = variant("C7171", lcsc="C906", jlc_type="Extended")
    p = pick_polar("tantalum", 1e-5, "A", [bad_v, bad_c, good], schema)
    assert p.part.lcsc == "C906"
    p = pick_polar("tantalum", 1e-5, "A", [bad_v], schema)
    assert p.part is None and "C904" in p.note


def test_pick_polar_rules(schema):
    unknown = variant("C7171", lcsc="C907", brand="Nobody", mpn="XYZ")
    low = variant("C7171", lcsc="C908", stock=10)
    other_case = variant("C16133", lcsc="C909")
    p = pick_polar("tantalum", 1e-5, "A", [unknown, low, other_case], schema)
    assert p.part is None and "unknown manufacturer" in p.note


def test_pick_polar_prefers_english(schema):
    a = variant("C7171", lcsc="C910", stock=900_000)
    b = variant("C7171", lcsc="C911", stock=5_000)
    lang = lambda p: Result("zh" if p.lcsc == "C910" else "en")  # noqa: E731
    p = pick_polar("tantalum", 1e-5, "A", [a, b], schema, lang=lang)
    assert p.part.lcsc == "C911" and p.datasheet.lang == "en"


def fake_search(by_value):
    def search(keyword, pages=2, post=None):
        return by_value.get(keyword.split()[0], [])
    return search


def lib_with_polar(minilib):
    shutil.copy(REPO / "src" / "symbols" / "passives.kicad_sym", minilib / "src" / "symbols" / "passives.kicad_sym")
    for f in ("CP_EIA-3216-18_Kemet-A",):
        shutil.copy(REPO / "footprints" / "LIB_Passives_SMD.pretty" / f"{f}.kicad_mod",
                    minilib / "footprints" / "LIB_Passives_SMD.pretty")
        for m in (REPO / "3dmodels" / "LIB_Passives_SMD.3dshapes").glob(f"{f}.*"):
            shutil.copy(m, minilib / "3dmodels" / "LIB_Passives_SMD.3dshapes")
    return minilib


RUN_TA = dict(kind="tantalum", series_name="E6", start=1e-5, stop=1.5e-5, package="A",
              max_tolerance=1.0, min_voltage=None, dielectrics=(), min_power=None)


def test_plan_tantalum_rows(minilib):
    root = lib_with_polar(minilib)
    rows = plan(root, **RUN_TA, search=fake_search({"10uF": [part("C7171")]}))
    assert [(r.value, r.status) for r in rows] == [("10uF", "new"), ("15uF", "none")]
    assert rows[0].name == "C_10u_CaseA_16V_Ta"


def test_write_tantalum_plan(minilib):
    root = lib_with_polar(minilib)
    rows = plan(root, **RUN_TA, search=fake_search({"10uF": [part("C7171")]}))
    save_plan(root, RUN_TA, rows)
    back, _ = load_plan(root, RUN_TA)
    assert apply(root, "tantalum", back) == 1
    assert "C_10u_CaseA_16V_Ta" in (root / "parts" / "capacitors.yaml").read_text(encoding="utf-8")
    assert [i for i in check(root, klc=False) if i.severity == "error"] == []
    # a second dry run sees the part as existing
    again = plan(root, **RUN_TA, search=fake_search({"10uF": [part("C7171")]}))
    assert again[0].status == "exists"


def test_cli_case_required(minilib, monkeypatch, capsys):
    from libkit import __main__ as cli
    monkeypatch.chdir(minilib)
    assert cli.main(["bulk-add", "tantalum", "--series", "E6", "--from", "1u", "--to", "10u"]) == 1
    err = capsys.readouterr().err
    assert "--case" in err and "A, B, C, D" in err

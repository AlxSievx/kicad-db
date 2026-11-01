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

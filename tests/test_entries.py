from dataclasses import replace
from datetime import date

import pytest
import yaml

from conftest import errors
from fakes import rec
from libkit import series
from libkit.entries import (footprint_for, kind_of, manufacturer_name, mpn_name, passive_entry,
                            passive_name)
from libkit.jlc import parse_record
from libkit.parts import Part, load_parts, validate, write_category

TODAY = date(2026, 11, 1)


def test_e12_decade():
    assert series.values("E12", 1000, 10000) == [1000, 1200, 1500, 1800, 2200, 2700, 3300, 3900,
                                                 4700, 5600, 6800, 8200, 10000]


def test_e96_count():
    assert len(series.values("E96", 100, 999)) == 96


def test_series_counts_and_members():
    assert [len(series.values(n, 1, 9.99)) for n in ("E6", "E12", "E24", "E48", "E96")] == [6, 12, 24, 48, 96]
    assert 4.99 in series.values("E96", 1, 10) and 1.02 in series.values("E96", 1, 10)
    assert series.values("E6", 1e-9, 1e-6) == pytest.approx([1e-9, 1.5e-9, 2.2e-9, 3.3e-9, 4.7e-9, 6.8e-9,
                                                              1e-8, 1.5e-8, 2.2e-8, 3.3e-8, 4.7e-8, 6.8e-8,
                                                              1e-7, 1.5e-7, 2.2e-7, 3.3e-7, 4.7e-7, 6.8e-7, 1e-6])
    assert series.values("E24", 2.7e3, 3.3e3) == [2700, 3000, 3300]  # E24 has 2.7, 3.0, 3.3


def test_series_values_are_clean():
    # 4.7k must come out as 4700, not 4699.999…, so names and lookups are exact.
    assert 4700 in series.values("E12", 1000, 10000)
    assert 4.7e-9 in series.values("E6", 1e-9, 1e-8) and 2.2e-12 in series.values("E6", 1e-12, 1e-11)


def test_unknown_series():
    with pytest.raises(ValueError):
        series.values("E7", 1, 10)


def test_bad_range():
    with pytest.raises(ValueError):
        series.values("E12", 10, 1)
    with pytest.raises(ValueError):
        series.values("E12", 0, 1)


def test_names():
    assert passive_name("resistor", 4700, "0603", tolerance=0.01) == "R_4.7k_0603_1pct"
    assert passive_name("resistor", 100, "0402", tolerance=0.005) == "R_100R_0402_0.5pct"
    assert passive_name("capacitor", 1e-7, "0402", voltage=16, dielectric="X7R") == "C_100n_0402_16V_X7R"
    assert passive_name("capacitor", 4.7e-6, "0805", voltage=6.3, dielectric="X5R") == "C_4.7u_0805_6.3V_X5R"
    assert passive_name("capacitor", 1e-11, "0402", voltage=50, dielectric="C0G") == "C_10p_0402_50V_C0G"


def test_names_missing_params():
    with pytest.raises(ValueError):
        passive_name("resistor", 4700, "0603")
    with pytest.raises(ValueError):
        passive_name("capacitor", 1e-7, "0402", voltage=16)
    with pytest.raises(ValueError):
        passive_name("inductor", 1e-6, "0402")


def test_footprint_for():
    assert footprint_for("capacitor", "0603") == "LIB_Passives_SMD:C_0603_1608Metric"
    assert footprint_for("resistor", "1206") == "LIB_Passives_SMD:R_1206_3216Metric"
    with pytest.raises(ValueError):
        footprint_for("resistor", "2512")


def test_passive_entry_from_jlc(schema):
    e = passive_entry("resistor", parse_record(rec("C25744")), schema, today=TODAY)
    assert e["name"] == "R_10k_0402_1pct"
    assert e["symbol"] == "R" and e["footprint"] == "LIB_Passives_SMD:R_0402_1005Metric"
    assert e["manufacturer"] == "UNI-ROYAL" and e["mpn"] == "0402WGF1002TCE" and e["lcsc"] == "C25744"
    assert e["value"] == "10k" and e["package"] == "0402" and e["jlc_type"] == "Basic"
    assert e["tolerance"] == "±1%" and e["power"] == "62.5mW" and e["tempco"] == "±100ppm/°C"
    assert e["datasheet"].startswith("https://www.lcsc.com/datasheet/")
    assert e["status"] == "active" and e["stock_checked"] == "2026-11-01" and int(e["stock"]) > 0
    assert all(isinstance(v, str) for v in e.values())
    p = Part(e["name"], "resistors", e, source=None)
    assert validate([p], schema) == []


def test_passive_entry_capacitor(schema):
    e = passive_entry("capacitor", parse_record(rec("C1525")), schema, today=TODAY)
    assert e["name"] == "C_100n_0402_16V_X7R" and e["value"] == "100nF" and e["symbol"] == "C"
    assert (e["voltage"], e["dielectric"], e["tolerance"]) == ("16V", "X7R", "±10%")
    assert e["manufacturer"] == "Samsung"
    assert validate([Part(e["name"], "capacitors", e, source=None)], schema) == []


def test_passive_entry_c0g(schema):
    e = passive_entry("capacitor", parse_record(rec("C32949")), schema, today=TODAY)
    assert e["name"] == "C_10p_0402_50V_C0G" and e["value"] == "10pF"


def test_passive_entry_unknown_brand_raises(schema):
    with pytest.raises(ValueError, match="C25744"):
        passive_entry("resistor", replace(parse_record(rec("C25744")), brand="NoName"), schema)


def test_passive_entry_missing_attribute_raises(schema):
    p = parse_record(rec("C25744"))
    with pytest.raises(ValueError, match="Tolerance"):
        passive_entry("resistor", replace(p, attributes={k: v for k, v in p.attributes.items() if k != "Tolerance"}),
                      schema)


def test_passive_entry_datasheet_fallback(schema):
    e = passive_entry("resistor", replace(parse_record(rec("C25744")), datasheet=""), schema)
    assert e["datasheet"] == "https://www.lcsc.com/datasheet/C25744.pdf"


def test_write_roundtrip_preserves_parts(minilib, schema):  # Review Focus 5
    before = load_parts(minilib, schema)
    new_entry = passive_entry("capacitor", replace(parse_record(rec("C1525")), lcsc="C99"), schema, today=TODAY)
    new_entry["name"] = "C_100n_0402_16V_X7R_b"
    old = [p.data for p in before if p.category == "capacitors"]
    write_category(minilib, "capacitors", old + [new_entry])
    after = load_parts(minilib, schema)
    assert [p.data for p in after if p.name != new_entry["name"]] == [p.data for p in before]
    assert next(p for p in after if p.name == new_entry["name"]).data == new_entry
    raw = (minilib / "parts" / "capacitors.yaml").read_bytes()
    assert b"\r\n" not in raw
    text = raw.decode("utf-8")
    assert "±10%" in text and "\\u" not in text
    assert 'package: "0402"' in text  # double quotes, like the hand-written files
    assert yaml.safe_load(text)["parts"][0]["package"] == "0402"  # still a string for a plain YAML reader
    assert yaml.safe_load(text)["parts"][0]["stock"] == "48200000"
    assert errors(minilib) == []


def test_write_field_order_and_style(minilib, schema):
    e = passive_entry("capacitor", parse_record(rec("C1525")), schema, today=TODAY)
    shuffled = dict(reversed(list(e.items())))
    write_category(minilib, "capacitors", [shuffled])
    lines = (minilib / "parts" / "capacitors.yaml").read_text(encoding="utf-8").splitlines()
    assert lines[0] == "parts:" and lines[1].startswith("  - name: C_100n_0402_16V_X7R")
    keys = [ln.split(":")[0].strip(" -") for ln in lines[1:]]
    assert keys[:5] == ["name", "symbol", "footprint", "value", "package"]
    assert keys[-3:] == ["voltage", "dielectric", "tolerance"]
    assert not list((minilib / "parts").glob("*.tmp"))


def test_write_empty_category(minilib):
    write_category(minilib, "inductors", [])
    assert (minilib / "parts" / "inductors.yaml").read_text(encoding="utf-8") == "parts: []\n"

@pytest.mark.parametrize("change", [
    {"attributes": {"Number of Resistors": "4", "Number of Pins": "8"}},
    {"description": "11kΩ 4 62.5mW 8 ±1% ±200ppm/℃ 1206 Resistor Networks, Arrays ROHS"},
])
def test_arrays_are_refused(schema, change):  # TC164 picked as an "1206 resistor"
    part = parse_record(rec("C25744"))
    if "attributes" in change:
        change = {"attributes": {**part.attributes, **change["attributes"]}}
    with pytest.raises(ValueError, match="array, not a single two-pin part"):
        passive_entry("resistor", replace(part, **change), schema, TODAY)


def test_single_chip_with_two_pins_is_fine(schema):
    part = parse_record(rec("C25744"))
    part = replace(part, attributes={**part.attributes, "Number of Resistors": "1", "Number of Pins": "2"})
    assert passive_entry("resistor", part, schema, TODAY)["name"] == "R_10k_0402_1pct"


def _validate_entry(schema, e):
    p = Part(e["name"], "inductors", e, None)
    return [i for i in validate([p], schema) if i.severity == "error"]


def test_kind_of():
    kinds = [kind_of(parse_record(rec(c))) for c in ("C25744", "C1525", "C1046", "C1015", "C6186")]
    assert kinds == ["resistor", "capacitor", "inductor", "bead", None]


def test_inductor_entry(schema):
    e = passive_entry("inductor", parse_record(rec("C1046")), schema, TODAY)
    assert e["name"] == "L_10u_0805_15mA"
    assert e["value"] == "10uH"
    assert e["symbol"] == "L"
    assert e["footprint"] == "LIB_Passives_SMD:L_0805_2012Metric"
    assert e["current_rating"] == "15mA"
    assert e["dcr"] == "1.15Ω"
    assert "current_sat" not in e
    assert _validate_entry(schema, e) == []


def test_bead_entry(schema):
    e = passive_entry("bead", parse_record(rec("C1015")), schema, TODAY)
    assert e["name"] == "FB_100R_0805_800mA"
    assert e["value"] == "100R@100MHz"
    assert e["symbol"] == "FerriteBead"
    assert e["footprint"] == "LIB_Passives_SMD:L_0805_2012Metric"
    assert e["current_rating"] == "800mA"
    assert e["dcr"] == "150mΩ"
    assert e["description"] == "100R@100MHz 800mA 0805 ferrite bead"
    assert _validate_entry(schema, e) == []


def test_power_inductor_needs_footprint(schema):
    part = parse_record(rec("C408412"))
    with pytest.raises(ValueError, match="footprint"):
        passive_entry("inductor", part, schema, TODAY)
    e = passive_entry("inductor", part, schema, TODAY, footprint="LIB_Inductor_SMD:L_Sunlord_MWSA0503S")
    assert e["name"] == "MWSA0503S-100MT"
    assert e["footprint"] == "LIB_Inductor_SMD:L_Sunlord_MWSA0503S"
    assert e["current_sat"] == "3.5A"
    assert e["current_rating"] == "3.2A"


@pytest.mark.parametrize("key", ["Current - Saturation (Isat)", "Current - Saturation(Isat)",
                                 "current - saturation(isat)"])
def test_attr_key_variants(schema, key):  # Review Focus 1
    part = parse_record(rec("C408412"))
    attrs = {k: v for k, v in part.attributes.items() if "isat" not in k.casefold()}
    e = passive_entry("inductor", replace(part, attributes={**attrs, key: "3.5A"}), schema, TODAY,
                      footprint="LIB_Inductor_SMD:X")
    assert e["current_sat"] == "3.5A"
    e = passive_entry("inductor", replace(part, attributes={**attrs, key: "-"}), schema, TODAY,
                      footprint="LIB_Inductor_SMD:X")
    assert "current_sat" not in e


def test_inductor_unicode_values(schema):
    part = parse_record(rec("C1046"))
    attrs = {**part.attributes, "Inductance": "4.7µH", "DC Resistance(DCR)": "1.15 Ω"}
    e = passive_entry("inductor", replace(part, attributes=attrs), schema, TODAY)
    assert e["value"] == "4.7uH" and e["name"] == "L_4.7u_0805_15mA"


@pytest.mark.parametrize("mpn,name", [("CKCS4018-4.7uH/M", "CKCS4018-4.7uH_M"),
                                      ("CD31 4R7M 4.7UH", "CD31_4R7M_4.7UH"),
                                      ("TPS62130RGTR", "TPS62130RGTR"),
                                      ("LTC1046CN8#PBF", "LTC1046CN8_PBF"),
                                      (" /X/ ", "X")])
def test_mpn_name_sanitized(mpn, name):  # Review Focus 2
    assert mpn_name(mpn) == name


def test_mpn_name_empty_refused():
    with pytest.raises(ValueError):
        mpn_name(" / ")


def test_unknown_brand_single_add(schema):
    assert manufacturer_name("AMS(Advanced Monolithic Systems)", schema) == ("AMS", False)
    assert manufacturer_name("UNI-ROYAL(Uniroyal Elec)", schema) == ("UNI-ROYAL", True)


def test_known_only_false_keeps_unknown_brand(schema):
    part = replace(parse_record(rec("C1046")), brand="NoName(Shenzhen NoName)")
    with pytest.raises(ValueError, match="not a known manufacturer"):
        passive_entry("inductor", part, schema, TODAY)
    assert passive_entry("inductor", part, schema, TODAY, known_only=False)["manufacturer"] == "NoName"

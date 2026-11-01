from conftest import VALID_CAP, errors, only_error, part, validate_one

from libkit.schema import load_schema


def test_schema_has_all_categories(schema):
    assert len(schema.categories) == 16
    cap = schema.categories["capacitors"]
    assert cap.lib_name == "LIB_Capacitors" and cap.value_unit == "F"
    assert [f.label for f in cap.fields] == ["Voltage", "Dielectric", "Tolerance"]
    assert schema.categories["leds_optoelectronics"].lib_name == "LIB_LEDs_Optoelectronics"
    assert schema.categories["mechanical"].orderable is False
    assert schema.families["Passives_SMD"].lib_name == "LIB_Passives_SMD"


def test_scalars_stay_strings(minilib):  # Review Focus 1
    p = part(minilib, "C_100n_0402_16V_X7R")
    assert p.data["package"] == "0402"
    assert p.data["stock_checked"] == "2026-10-30"
    assert p.data["stock"] == "48200000"
    assert p.category == "capacitors"


def test_valid_fixture_has_no_errors(minilib):
    assert errors(minilib) == []


def test_valid_part_has_no_issues():
    assert validate_one({}) == []


def test_missing_mpn_is_error():
    assert "mpn" in only_error(validate_one({"mpn": None}))


def test_empty_value_counts_as_missing():
    assert "mpn" in only_error(validate_one({"mpn": ""}))


def test_missing_category_field_is_error():
    assert "dielectric" in only_error(validate_one({"dielectric": None}))


def test_mechanical_needs_no_mpn():
    base = {"name": "MountingHole_M3", "symbol": "MountingHole", "footprint": "LIB_Mechanical:MountingHole_3.2mm_M3",
            "value": "M3", "package": "M3", "description": "M3 mounting hole", "status": "active"}
    assert validate_one({}, category="mechanical", base=base) == []


def test_description_required_without_template():
    base = {k: v for k, v in VALID_CAP.items() if k not in ("voltage", "dielectric", "tolerance")}
    assert "description" in only_error(validate_one({}, category="ics_power", base=base))


def test_bad_lcsc_format():
    assert "lcsc" in only_error(validate_one({"lcsc": "1525"}))


def test_bad_enum():
    assert "jlc_type" in only_error(validate_one({"jlc_type": "basic"}))


def test_bad_url():
    assert "datasheet" in only_error(validate_one({"datasheet": "www.example.com/x.pdf"}))


def test_bad_int_and_date():
    assert "stock" in only_error(validate_one({"stock": "lots"}))
    assert "stock_checked" in only_error(validate_one({"stock_checked": "30.10.2026"}))


def test_unknown_field_is_error():
    assert "colour" in only_error(validate_one({"colour": "red"}))


def test_unknown_manufacturer_is_warning():
    issues = validate_one({"manufacturer": "NoName"})
    assert [i.severity for i in issues] == ["warning"]


def test_duplicate_names_across_files(minilib):  # Review Focus 5
    f = minilib / "parts" / "resistors.yaml"
    f.write_text(f.read_text(encoding="utf-8") + "  - name: C_100n_0402_16V_X7R\n", encoding="utf-8")
    assert any("duplicate" in i.message for i in errors(minilib))


def test_unknown_parts_file_is_error(minilib):
    (minilib / "parts" / "capacitor.yaml").write_text("parts: []\n", encoding="utf-8")
    assert any("capacitor.yaml" in i.message for i in errors(minilib))


def test_missing_category_file_is_empty_category(minilib):
    assert not (minilib / "parts" / "inductors.yaml").exists()
    assert errors(minilib) == []


def test_real_repo_schema_and_parts_load():
    from conftest import REPO
    s = load_schema(REPO)
    assert errors(REPO) == []
    assert set(s.categories) == {p.stem for p in (REPO / "parts").glob("*.yaml")}


def test_illegal_name_characters():  # KLC G1.1 allows only letters, digits and _-.+,
    assert "name" in only_error(validate_one({"name": "R_10k_0402_1%"}))
    assert validate_one({"name": "R_10k_0402_1pct"}) == []


def test_unknown_manufacturer_ok_outside_passives():
    base = {k: v for k, v in VALID_CAP.items() if k not in ("voltage", "dielectric", "tolerance")}
    ic = {**base, "name": "TPS62130RGTR", "manufacturer": "Texas Instruments", "description": "buck converter"}
    assert validate_one({}, category="ics_power", base=ic) == []


def test_malformed_yaml_is_clear_error(minilib):
    import pytest
    from libkit.parts import load_parts
    from libkit.schema import load_schema
    (minilib / "parts" / "diodes.yaml").write_text("parts:\n  - name: D1\n   bad: [\n", encoding="utf-8")
    with pytest.raises(ValueError, match="diodes.yaml"):
        load_parts(minilib, load_schema(minilib))
    (minilib / "parts" / "diodes.yaml").write_text("parts:\n  - just a string\n", encoding="utf-8")
    with pytest.raises(ValueError, match="diodes.yaml"):
        load_parts(minilib, load_schema(minilib))


def test_cli_malformed_yaml_no_traceback(minilib):
    import subprocess
    import sys
    (minilib / "parts" / "diodes.yaml").write_text("parts:\n  - name: D1\n   bad: [\n", encoding="utf-8")
    for cmd in (["build"], ["check", "--no-klc"]):
        r = subprocess.run([sys.executable, "-m", "libkit", *cmd], cwd=minilib, capture_output=True, text=True)
        assert r.returncode == 1 and "diodes.yaml" in r.stderr and "Traceback" not in r.stderr, r.stderr

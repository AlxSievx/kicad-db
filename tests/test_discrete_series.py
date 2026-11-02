"""Plan 8: discrete package map, discrete manufacturers, bulk add of MPN series."""

from dataclasses import replace

import pytest

from conftest import REPO
from fakes import rec
from libkit.discretes import FOOTPRINTS, canonical_package, classify, stock_footprint
from libkit.jlc import parse_record
from libkit.schema import load_schema


def part(code):
    return parse_record(rec(code))


@pytest.fixture
def schema():
    return load_schema(REPO)


# ---- Task 1 ----------------------------------------------------------------------------------------
def test_stock_footprint_spellings():  # Review Focus 2
    diode = part("C81598")
    for pkg in ("SMA(DO-214AC)", "DO-214AC(SMA)", "SMA", "DO-214AC"):
        assert stock_footprint(replace(diode, package=pkg)) == ("Diode_SMD:D_SMA", "Diode_SMD"), pkg
    assert stock_footprint(replace(diode, package="DO-214AA(SMB)"))[0] == "Diode_SMD:D_SMB"
    assert stock_footprint(replace(diode, package="SOD-123FL"))[0] == "Diode_SMD:D_SOD-123F"
    assert canonical_package(replace(diode, package="SOD-123F")) == "SOD-123F"
    assert stock_footprint(replace(diode, package="SMAF")) is None
    assert stock_footprint(part("C20917")) == ("Package_TO_SOT_SMD:SOT-23", "Package_TO_SOT_SMD")
    assert stock_footprint(replace(part("C20917"), package="TO-236"))[0] == "Package_TO_SOT_SMD:SOT-23"
    assert stock_footprint(part("C2286")) == ("LED_SMD:LED_0603_1608Metric", "LED_SMD")
    assert stock_footprint(part("C1525")) is None  # a 0402 capacitor is no LED
    assert canonical_package(replace(part("C1525"), package="0603")) is None
    assert set(FOOTPRINTS) >= {"SOD-123", "SOD-323", "SMA", "SMB", "SMC", "SOT-23", "LED-0603"}


def _tvs(polarity, channels="Single-channel"):
    p = part("C78402")
    attrs = dict(p.attributes, Polarity=polarity)
    attrs["Number of Channels"] = channels
    return replace(p, attributes=attrs)


def test_unidirectional_tvs_is_zener_symbol():
    d = classify(_tvs("Unidirectional"))
    assert (d.symbol, d.category) == ("D_Zener", "diodes") and d.fields["vr"] == "5V"
    assert "cathode" in d.checklist
    assert classify(_tvs("Bidirectional")).symbol == "D_TVS"
    assert classify(_tvs("Unidirectional", "2")).symbol is None


def test_add_defaults_stock_footprint(minilib):
    from test_add import prep
    root = _with_bases(minilib)

    def no_fetch(lcsc, workdir):
        raise AssertionError("EasyEDA must not be fetched")

    p = prep(root, "C81598", fetch=no_fetch)
    assert p.entry["footprint"] == "LIB_Diode_SMD:D_SOD-123" and p.new_family == "Diode_SMD"
    assert p.entry["symbol"] == "D"


def _with_bases(minilib):
    import shutil
    for f in ("passives.kicad_sym", "discretes.kicad_sym", "mechanical.kicad_sym"):
        shutil.copy(REPO / "src" / "symbols" / f, minilib / "src" / "symbols" / f)
    return minilib


# ---- Task 2 ----------------------------------------------------------------------------------------
def test_discrete_manufacturers(schema):  # Review Focus 3
    c = schema.canonical_manufacturer
    assert c("Jiangsu Changjing Electronics Technology Co., Ltd.") == "CJ"
    assert c("MDD(Microdiode Semiconductor)") == "MDD"
    assert c("Hubei KENTO Elec") == "KENTO"
    assert c("Alpha & Omega Semicon") == "AOS"
    assert c("hongjiacheng") == "hongjiacheng"
    assert c("STMicroelectronics") == "STMicroelectronics"
    assert c("Vishay Intertech") == "Vishay"
    assert c("ST(Semtech)") is None
    assert c("cjiang") == "cjiang"


# ---- Task 3 ----------------------------------------------------------------------------------------
from libkit.discrete_series import series_member  # noqa: E402
from libkit.pick import pick_discrete  # noqa: E402

SHARE = REPO / "tests" / "fixtures" / "share"


def zener(mpn, lcsc, package="SOD-123", brand="hongjiacheng", jlc_type="Preferred", stock=50_000, vz="3.3V"):
    p = part("C8056")
    return replace(p, mpn=mpn, lcsc=lcsc, package=package, brand=brand, jlc_type=jlc_type, stock=stock,
                   attributes=dict(p.attributes, **{"Zener Voltage(Nom)": vz}))


def test_series_member():  # Review Focus 1
    assert series_member("BZT52C3V3", "BZT52C3V3") and series_member("BZT52C3V3", "bzt52c3v3-7-F")
    assert not series_member("BZT52C3V3", "BZT52C3V3S")
    assert series_member("SMAJ5.0A", "SMAJ5.0A/TR13") and not series_member("SMAJ5.0A", "SMAJ5.0CA")
    assert not series_member("SS14", "SS14F") and not series_member("SS14", "SS1")


def test_mpn_values():
    from libkit.series import mpn_values
    z = mpn_values("zener")
    assert z[0] == "2V4" and z[-1] == "51" and len(z) == 33
    t = mpn_values("tvs")
    assert t[0] == "5.0" and t[-1] == "100" and len(t) == 40
    assert mpn_values("14, 16,110") == ["14", "16", "110"]
    with pytest.raises(ValueError):
        mpn_values("")


def test_pick_rejects_other_package(schema):  # Review Focus 2
    other = zener("BZT52C3V3", "C901", package="SOD-123F")
    p = pick_discrete("BZT52C3V3", "SOD-123", [other], schema)
    assert p.part is None and "package" in p.note


def test_pick_discrete_order(schema):
    pref = zener("BZT52C3V3", "C902", stock=10_000)
    ext = zener("BZT52C3V3-7-F", "C903", brand="Diodes Incorporated", jlc_type="Extended", stock=1_000_000)
    pref2 = zener("BZT52C3V3", "C904", brand="MDD(Microdiode Semiconductor)", stock=20_000)
    nobody = zener("BZT52C3V3", "C905", brand="Nobody", jlc_type="Basic", stock=9_000_000)
    neighbour = zener("BZT52C3V3S", "C906", jlc_type="Basic", stock=9_000_000)
    assert pick_discrete("BZT52C3V3", "SOD-123", [ext, pref], schema).part.lcsc == "C902"
    assert pick_discrete("BZT52C3V3", "SOD-123", [pref, pref2, nobody, neighbour], schema).part.lcsc == "C904"
    p = pick_discrete("BZT52C3V3", "SOD-123", [nobody], schema)
    assert p.part is None and "unknown manufacturer" in p.note


def _dlib(minilib):
    return _with_bases(minilib)


def fake_search(parts):
    def search(keyword, pages=2, post=None):
        return [p for p in parts if p.mpn.upper().startswith(keyword.upper())]
    return search


def no_fetch(lcsc, workdir):
    raise AssertionError("EasyEDA must not be fetched in bulk")


def test_row_without_base_symbol(minilib):  # Review Focus 4
    from libkit.discrete_series import plan
    dual = replace(part("C8592"), mpn="BAT54S", brand="hongjiacheng", jlc_type="Preferred", stock=50_000)
    rows = plan(_dlib(minilib), "BAT54{}", ["S"], "SOT-23", search=fake_search([dual]), kicad_share_dir=SHARE,
                fetch=no_fetch)
    assert rows[0].status == "none" and "single add" in rows[0].note


def _two_zeners():
    return [zener("BZT52C3V3", "C19077396"), zener("BZT52C5V1", "C19077401", vz="5.1V")]


def test_plan_and_write_discrete(minilib):
    from libkit.check import check
    from libkit.discrete_series import apply, load_plan, plan, save_plan
    root = _dlib(minilib)
    run = dict(pattern="BZT52C{}", values=["3V3", "5V1"], package="SOD-123")
    rows = plan(root, **run, search=fake_search(_two_zeners()), kicad_share_dir=SHARE, fetch=no_fetch)
    assert [(r.value, r.name, r.status) for r in rows] == [("3V3", "BZT52C3V3", "new"), ("5V1", "BZT52C5V1", "new")]
    assert rows[1].entry["vz"] == "5.1V" and rows[1].entry["symbol"] == "D_Zener"
    assert rows[0].entry["footprint"] == "LIB_Diode_SMD:D_SOD-123"
    save_plan(root, run, rows)
    back, _ = load_plan(root, run)
    assert apply(root, run, back) == 2
    text = (root / "parts" / "diodes.yaml").read_text(encoding="utf-8")
    assert "BZT52C3V3" in text and "BZT52C5V1" in text
    assert (root / "footprints" / "LIB_Diode_SMD.pretty" / "D_SOD-123.kicad_mod").exists()
    assert "Diode_SMD" in load_schema(root).families
    assert [i for i in check(root, klc=False) if i.severity == "error"] == []
    again = plan(root, **run, search=fake_search(_two_zeners()), kicad_share_dir=SHARE, fetch=no_fetch)
    assert [r.status for r in again] == ["exists", "exists"]
    with pytest.raises(ValueError, match="changed"):
        load_plan(root, run)


def test_skip_discrete_rows():
    from libkit.bulk import Row
    from libkit.discrete_series import skip_rows
    rows = [Row("3V3", "BZT52C3V3", "new", {}, ""), Row("5V1", "BZT52C5V1", "new", {}, "")]
    assert [r.status for r in skip_rows(rows, ["5v1"])] == ["new", "skipped"]
    with pytest.raises(ValueError, match="5V6"):
        skip_rows(rows, ["5V6"])


def test_apply_many_rolls_back(minilib):  # Review Focus 5
    from libkit.add import apply_many, load_plan as load_add
    from libkit.discrete_series import plan, plan_options
    from test_add import snapshot
    root = _dlib(minilib)
    from libkit.build import build
    build(root)
    rows = plan(root, "BZT52C{}", ["3V3", "5V1"], "SOD-123", search=fake_search(_two_zeners()),
                kicad_share_dir=SHARE, fetch=no_fetch)
    opts = plan_options("SOD-123")
    plans = [load_add(root, r.entry["lcsc"], opts) for r in rows]
    plans[1].entry["vz"] = None  # not a string: the second part breaks the YAML/validation
    plans[1].entry.pop("lcsc")
    before = snapshot(root)
    with pytest.raises(Exception):
        apply_many(root, plans)
    assert snapshot(root) == before


def test_cli_discrete_options(minilib, monkeypatch, capsys):
    from libkit import __main__ as cli
    monkeypatch.chdir(minilib)
    assert cli.main(["bulk-add", "discrete", "--mpn", "BZT52C{}", "--values", "zener"]) == 1
    assert "SOD-123" in capsys.readouterr().err  # --package missing: the list is shown
    assert cli.main(["bulk-add", "discrete", "--mpn", "BZT52C", "--values", "zener", "--package", "SOD-123"]) == 1
    assert "{}" in capsys.readouterr().err
    assert cli.main(["bulk-add", "resistor", "--package", "0402", "--tolerance", "1%"]) == 1
    assert "--series" in capsys.readouterr().err


# ---- final review fixes ---------------------------------------------------------------------------
def test_no_stock_footprint_without_base_symbol(minilib):  # final review I2
    from test_add import prep
    root = _with_bases(minilib)
    p = prep(root, "C8592", family="Package_TO_SOT", fp_name="SOT-23")  # dual diode: EasyEDA footprint too
    assert not p.entry["footprint"].startswith("LIB_Package_TO_SOT_SMD") and p.symbol is not None
    p = prep(root, "C81598", family="Diode_SMD", fp_name="D_Odd")  # --fp-name means an EasyEDA footprint
    assert p.entry["footprint"] == "LIB_Diode_SMD:D_Odd"


def test_stock_symbol_takes_stock_footprint(minilib, tmp_path):
    import shutil
    from libkit.kicad import kicad_share
    from test_add import prep
    diode_lib = kicad_share() / "symbols" / "Diode.kicad_sym"
    if not diode_lib.exists():
        pytest.skip("needs the installed KiCad symbol libraries")
    share = tmp_path / "share"
    shutil.copytree(SHARE, share)
    (share / "symbols").mkdir()
    shutil.copy(diode_lib, share / "symbols")
    p = prep(_with_bases(minilib), "C8592", symbol="stock:Diode:BAT54S", kicad_share_dir=share)
    assert p.entry["footprint"] == "LIB_Package_TO_SOT_SMD:SOT-23" and p.symbol is not None

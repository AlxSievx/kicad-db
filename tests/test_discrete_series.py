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

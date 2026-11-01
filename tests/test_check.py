import shutil
from pathlib import Path

import pytest

from libkit.build import build
from libkit.check import check
from libkit.klc import klc_dir, run_klc

REPO = Path(__file__).resolve().parents[1]
klc_present = pytest.mark.skipif(not (klc_dir(REPO) / "klc-check").exists(),
                                 reason="run `python -m libkit fetch-klc` first")


@pytest.fixture
def built_minilib(minilib):
    build(minilib)
    return minilib


def msgs(root, **kw):
    return [i.message for i in check(root, klc=False, **kw) if i.severity == "error"]


def edit(path: Path, old: str, new: str):
    t = path.read_text(encoding="utf-8")
    assert old in t, old
    path.write_text(t.replace(old, new), encoding="utf-8", newline="\n")


def test_clean_minilib(built_minilib):
    assert check(built_minilib, klc=False) == []


def test_validation_errors_reported(built_minilib):
    edit(built_minilib / "parts" / "capacitors.yaml", "    mpn: CL05B104KO5NNNC\n", "")
    assert any("mpn" in m for m in msgs(built_minilib))


def test_stale_generated(built_minilib):
    edit(built_minilib / "parts" / "capacitors.yaml", "value: 100nF", "value: 220nF")
    assert any("stale" in m and "LIB_Capacitors" in m for m in msgs(built_minilib))


def test_never_built_is_stale(minilib):
    assert any("stale" in m for m in msgs(minilib))


def test_up_to_date_ignores_crlf(built_minilib):  # Review Focus 4
    f = built_minilib / "symbols" / "LIB_Capacitors.kicad_sym"
    f.write_bytes(f.read_bytes().replace(b"\n", b"\r\n"))
    assert check(built_minilib, klc=False) == []


def test_missing_footprint(built_minilib):
    (built_minilib / "footprints" / "LIB_Passives_SMD.pretty" / "C_0402_1005Metric.kicad_mod").unlink()
    assert any("footprint" in m and "C_0402_1005Metric" in m for m in msgs(built_minilib))


def test_undeclared_footprint_library(built_minilib):
    edit(built_minilib / "parts" / "capacitors.yaml", "LIB_Passives_SMD:C_0402", "LIB_Other:C_0402")
    build_ok = msgs(built_minilib)
    assert any("LIB_Other" in m for m in build_ok)


def test_undeclared_pretty_dir(built_minilib):
    (built_minilib / "footprints" / "LIB_Stray.pretty").mkdir()
    assert any("LIB_Stray" in m for m in msgs(built_minilib))


def test_missing_3d_model(built_minilib):
    (built_minilib / "3dmodels" / "LIB_Passives_SMD.3dshapes" / "C_0402_1005Metric.step").unlink()
    assert any("3D model" in m for m in msgs(built_minilib))


def test_model_without_lib_dir(built_minilib):
    edit(built_minilib / "footprints" / "LIB_Passives_SMD.pretty" / "C_0402_1005Metric.kicad_mod",
         "${LIB_DIR}/3dmodels", "${KICAD10_3DMODEL_DIR}/3dmodels")
    assert any("${LIB_DIR}" in m for m in msgs(built_minilib))


def test_absolute_path_flagged(built_minilib):
    edit(built_minilib / "footprints" / "LIB_Passives_SMD.pretty" / "R_0402_1005Metric.kicad_mod",
         '(model "${LIB_DIR}/3dmodels/LIB_Passives_SMD.3dshapes/R_0402_1005Metric.step"',
         '(model "C:/x/R_0402_1005Metric.step"')
    assert any("absolute" in m for m in msgs(built_minilib))


def test_klc_missing_is_error(built_minilib):
    issues = check(built_minilib, klc=True)
    assert any("fetch-klc" in i.message for i in issues if i.severity == "error")


@klc_present
def test_klc_stock_footprint_clean_with_allowlist(built_minilib):
    fp = built_minilib / "footprints" / "LIB_Passives_SMD.pretty" / "C_0402_1005Metric.kicad_mod"
    issues = run_klc(REPO, [fp])
    assert [i for i in issues if i.severity == "error"] == []


@klc_present
def test_klc_reports_bad_footprint(built_minilib):
    fp = built_minilib / "footprints" / "LIB_Passives_SMD.pretty" / "C_0402_1005Metric.kicad_mod"
    bad = fp.with_name("C_BAD.kicad_mod")
    shutil.copyfile(fp, bad)
    # thin silkscreen line straight across both pads
    edit(bad, '(attr smd)', '(attr smd)\n\t(fp_line (start -1 0) (end 1 0) (stroke (width 0.05) (type solid)) (layer "F.SilkS"))')
    issues = run_klc(REPO, [bad])
    assert any(i.severity == "error" and i.message.startswith("KLC F") for i in issues), issues


@klc_present
def test_klc_symbol_allowlist_scoped_to_stock_bases(built_minilib):
    # Base C is allow-listed for S4.1 (110 mil pins); a non-stock symbol with the same pins is not.
    lib = built_minilib / "symbols" / "LIB_Capacitors.kicad_sym"
    issues = run_klc(REPO, [lib])
    assert not [i for i in issues if i.severity == "error"], issues
    t = lib.read_text(encoding="utf-8").replace('(symbol "C"', '(symbol "MYCAP"').replace('(symbol "C_0_1"', '(symbol "MYCAP_0_1"').replace('(symbol "C_1_1"', '(symbol "MYCAP_1_1"').replace('(extends "C")', '(extends "MYCAP")')
    other = lib.with_name("LIB_Other.kicad_sym")
    other.write_text(t, encoding="utf-8")
    assert any("S4.1" in i.message for i in run_klc(REPO, [other]))


def test_cli_check_exit_codes(built_minilib):
    import subprocess
    import sys
    run = lambda: subprocess.run([sys.executable, "-m", "libkit", "check", "--no-klc"],
                                 cwd=built_minilib, capture_output=True, text=True)
    r = run()
    assert r.returncode == 0 and "0 errors" in r.stdout, r.stdout + r.stderr
    edit(built_minilib / "parts" / "capacitors.yaml", "value: 100nF", "value: 220nF")
    r = run()
    assert r.returncode == 1 and "stale" in r.stderr

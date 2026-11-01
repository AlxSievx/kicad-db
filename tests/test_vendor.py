import pytest

from libkit.kicad import kicad_share
from libkit.schema import Family
from libkit.sexpr import find_all, parse
from libkit.vendor import vendor_footprint, vendor_symbol

share_ok = pytest.mark.skipif(not (kicad_share() / "symbols" / "Device.kicad_sym").exists(),
                              reason="KiCad stock libraries not installed")
FAM = Family("Passives_SMD", "LIB_Passives_SMD")


@pytest.fixture
def root(tmp_path):
    return tmp_path / "lib"


@pytest.fixture
def dest(root):
    return root / "src" / "symbols" / "passives.kicad_sym"


def names(dest):
    return [str(s[1]) for s in find_all(parse(dest.read_text(encoding="utf-8")), "symbol")]


@share_ok
def test_footprint_model_path_rewritten(root):
    fp = vendor_footprint("Capacitor_SMD:C_0402_1005Metric", FAM, root, kicad_share())
    assert fp == root / "footprints" / "LIB_Passives_SMD.pretty" / "C_0402_1005Metric.kicad_mod"
    t = fp.read_text(encoding="utf-8")
    assert '"${LIB_DIR}/3dmodels/LIB_Passives_SMD.3dshapes/C_0402_1005Metric.step"' in t
    assert "KICAD10_" not in t
    assert (root / "3dmodels" / "LIB_Passives_SMD.3dshapes" / "C_0402_1005Metric.step").stat().st_size > 1000


@share_ok
def test_footprint_missing_model_raises(root, tmp_path):
    share = tmp_path / "share"
    (share / "footprints" / "X.pretty").mkdir(parents=True)
    (share / "footprints" / "X.pretty" / "F.kicad_mod").write_text(
        '(footprint "F" (model "${KICAD10_3DMODEL_DIR}/X.3dshapes/F.step"))\n', encoding="utf-8")
    with pytest.raises(FileNotFoundError):
        vendor_footprint("X:F", FAM, root, share)


def test_unknown_footprint_raises(root, tmp_path):
    with pytest.raises(FileNotFoundError):
        vendor_footprint("Nope:Nothing", FAM, root, tmp_path)


@share_ok
def test_vendor_symbol_idempotent(dest):
    vendor_symbol("Device:C", dest, kicad_share())
    vendor_symbol("Device:C", dest, kicad_share())
    assert names(dest) == ["C"]
    head = parse(dest.read_text(encoding="utf-8"))
    assert head[0] == "kicad_symbol_lib"


@share_ok
def test_vendor_symbol_brings_parent(dest):  # Device:Filter_EMI_C extends C_Feedthrough
    vendor_symbol("Device:Filter_EMI_C", dest, kicad_share())
    assert names(dest) == ["C_Feedthrough", "Filter_EMI_C"]


@share_ok
def test_vendor_symbol_unknown_raises(dest):
    with pytest.raises(KeyError):
        vendor_symbol("Device:DoesNotExist", dest, kicad_share())


def run_cli(root, *args):
    import subprocess
    import sys
    return subprocess.run([sys.executable, "-m", "libkit", *args], cwd=root, capture_output=True, text=True)


@share_ok
def test_cli_vendor_commands(minilib):
    r = run_cli(minilib, "vendor-sym", "Device:L", "--into", "passives")
    assert r.returncode == 0, r.stderr
    assert "L" in names(minilib / "src" / "symbols" / "passives.kicad_sym")
    r = run_cli(minilib / "parts", "vendor-fp", "Inductor_SMD:L_0402_1005Metric", "--family", "Passives_SMD")
    assert r.returncode == 0, r.stderr  # run from a subfolder: root is found by walking up
    assert (minilib / "footprints" / "LIB_Passives_SMD.pretty" / "L_0402_1005Metric.kicad_mod").exists()


def test_cli_unknown_family_fails(minilib):
    r = run_cli(minilib, "vendor-fp", "Inductor_SMD:L_0402_1005Metric", "--family", "Nope")
    assert r.returncode == 1 and "Nope" in r.stderr

import subprocess
import sys

import pytest

from libkit.build import BuildError, build, generate
from libkit.sexpr import find_all, parse


def run_cli(root, *args):
    return subprocess.run([sys.executable, "-m", "libkit", *args], cwd=root, capture_output=True, text=True)


def drop_mpn(root):
    f = root / "parts" / "capacitors.yaml"
    f.write_text(f.read_text(encoding="utf-8").replace("    mpn: CL05B104KO5NNNC\n", ""), encoding="utf-8")


def test_generate_paths(minilib):
    g = generate(minilib)
    assert {"sym-lib-table", "fp-lib-table", "symbols/LIB_Capacitors.kicad_sym",
            "symbols/LIB_Modules.kicad_sym"} <= set(g)
    assert len([k for k in g if k.startswith("symbols/")]) == 16


def test_sym_table(minilib):
    t = parse(generate(minilib)["sym-lib-table"])
    assert t[0] == "sym_lib_table" and ["version", "7"] in t
    libs = {str(l[1][1]): l for l in find_all(t, "lib")}
    assert len(libs) == 16
    cap = libs["LIB_Capacitors"]
    assert ["type", "KiCad"] in cap
    assert ["uri", "${LIB_DIR}/symbols/LIB_Capacitors.kicad_sym"] in cap
    assert ["descr", "Capacitors"] in cap


def test_fp_table(minilib):
    t = parse(generate(minilib)["fp-lib-table"])
    assert t[0] == "fp_lib_table"
    (lib,) = find_all(t, "lib")
    assert ["name", "LIB_Passives_SMD"] in lib
    assert ["uri", "${LIB_DIR}/footprints/LIB_Passives_SMD.pretty"] in lib


def test_build_refuses_invalid(minilib):
    drop_mpn(minilib)
    with pytest.raises(BuildError) as ei:
        generate(minilib)
    assert any("mpn" in i.message for i in ei.value.issues)


def test_build_refuses_unknown_symbol(minilib):
    f = minilib / "parts" / "capacitors.yaml"
    f.write_text(f.read_text(encoding="utf-8").replace("symbol: C\n", "symbol: NOPE\n"), encoding="utf-8")
    with pytest.raises(BuildError) as ei:
        generate(minilib)
    assert any("NOPE" in i.message for i in ei.value.issues)


def test_warnings_do_not_block(minilib):
    f = minilib / "parts" / "capacitors.yaml"
    f.write_text(f.read_text(encoding="utf-8").replace("manufacturer: Samsung", "manufacturer: NoName"), encoding="utf-8")
    assert "symbols/LIB_Capacitors.kicad_sym" in generate(minilib)


def test_build_writes_files(minilib):
    written = build(minilib)
    assert (minilib / "symbols" / "LIB_Capacitors.kicad_sym").exists()
    assert len(written) == 18
    assert b"\r\n" not in (minilib / "sym-lib-table").read_bytes()


def test_cli_build_exit_codes(minilib):
    r = run_cli(minilib, "build")
    assert r.returncode == 0, r.stderr
    drop_mpn(minilib)
    r = run_cli(minilib, "build")
    assert r.returncode == 1
    assert "ERROR C_100n_0402_16V_X7R" in r.stdout + r.stderr

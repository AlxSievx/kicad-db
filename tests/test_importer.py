import shutil
import subprocess
from pathlib import Path

import pytest

from libkit import kicad
from libkit.importer import fetch_easyeda
from libkit.net import NetError
from libkit.schema import Family
from libkit.sexpr import parse
from libkit.vendor import vendor_footprint

FIX = Path(__file__).parent / "fixtures" / "easyeda" / "C6186"


def fake_run(calls=None):
    def run(cmd, **kw):
        if calls is not None:
            calls.append((cmd, kw))
        shutil.copytree(FIX / "raw", kw["cwd"], dirs_exist_ok=True)
        return subprocess.CompletedProcess(cmd, 0, "", "")
    return run


def fake_upgrade(kind, src, dst, run=None):
    rel = Path(src).name
    if Path(src).is_dir():
        shutil.copytree(FIX / "up" / rel, dst)
    else:
        Path(dst).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(FIX / "up" / rel, dst)


def test_fetch_easyeda_offline(tmp_path):
    calls = []
    f = fetch_easyeda("C6186", tmp_path / "w", run=fake_run(calls), upgrade=fake_upgrade)
    assert str(f.symbol[1]) == "AMS1117-3.3"
    assert str(f.footprint[0]) == "footprint"
    assert f.footprint_name == "SOT-223-3_L6.5-W3.4-P2.30-LS7.0-BR"
    assert f.step.suffix == ".step" and f.step.exists()
    cmd, kw = calls[0]
    assert cmd[1:] == ["-m", "easyeda2kicad", "--full", "--lcsc_id", "C6186", "--output",
                       str(tmp_path / "w" / "E2K")]
    assert kw["cwd"] == tmp_path / "w" and kw["timeout"] == 120


def test_fetch_easyeda_nothing_written(tmp_path):
    def run(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 1, "", "[ERROR] Failed to fetch data from EasyEDA API")
    with pytest.raises(NetError, match="C6186.*no files.*EasyEDA API"):
        fetch_easyeda("C6186", tmp_path, run=run, upgrade=fake_upgrade)


def test_fetch_easyeda_timeout(tmp_path):
    def run(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, 120)
    with pytest.raises(NetError, match="C6186"):
        fetch_easyeda("C6186", tmp_path, run=run, upgrade=fake_upgrade)


def test_upgrade_runs_kicad_cli(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(kicad, "find_kicad_cli", lambda: Path("kicad-cli.exe"))

    def run(cmd, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")
    kicad.upgrade("fp", tmp_path / "a.pretty", tmp_path / "b.pretty", run=run)
    assert calls == [["kicad-cli.exe", "fp", "upgrade", str(tmp_path / "a.pretty"), "-o",
                      str(tmp_path / "b.pretty"), "--force"]]


def test_upgrade_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(kicad, "find_kicad_cli", lambda: Path("kicad-cli.exe"))
    with pytest.raises(ValueError, match="boom"):
        kicad.upgrade("sym", tmp_path / "a", tmp_path / "b",
                      run=lambda cmd, **kw: subprocess.CompletedProcess(cmd, 3, "", "boom"))


def test_upgrade_without_kicad(tmp_path, monkeypatch):
    monkeypatch.setattr(kicad, "find_kicad_cli", lambda: None)
    with pytest.raises(FileNotFoundError, match="kicad-cli"):
        kicad.upgrade("sym", tmp_path / "a", tmp_path / "b")


def test_vendor_footprint_into_staging(tmp_path):
    share = tmp_path / "share"
    (share / "footprints" / "Package_TO_SOT_SMD.pretty").mkdir(parents=True)
    (share / "3dmodels" / "Package_TO_SOT_SMD.3dshapes").mkdir(parents=True)
    (share / "footprints" / "Package_TO_SOT_SMD.pretty" / "SOT-223.kicad_mod").write_text(
        '(footprint "SOT-223" (model "${KICAD10_3DMODEL_DIR}/Package_TO_SOT_SMD.3dshapes/SOT-223.step"))\n',
        encoding="utf-8")
    (share / "3dmodels" / "Package_TO_SOT_SMD.3dshapes" / "SOT-223.step").write_text("step", encoding="utf-8")
    root, stage = tmp_path / "lib", tmp_path / "stage"
    out = vendor_footprint("Package_TO_SOT_SMD:SOT-223", Family("Package_TO_SOT", "LIB_Package_TO_SOT"), root,
                           share, dest_dir=stage, models_dir=stage)
    assert out == stage / "SOT-223.kicad_mod"
    assert (stage / "SOT-223.step").exists()
    assert '"${LIB_DIR}/3dmodels/LIB_Package_TO_SOT.3dshapes/SOT-223.step"' in out.read_text(encoding="utf-8")
    assert not root.exists()


@pytest.mark.kicad
def test_upgrade_real(tmp_path):
    if kicad.find_kicad_cli() is None:
        pytest.skip("kicad-cli not installed")
    kicad.upgrade("fp", FIX / "raw" / "E2K.pretty", tmp_path / "o.pretty")
    text = (tmp_path / "o.pretty" / "SOT-223-3_L6.5-W3.4-P2.30-LS7.0-BR.kicad_mod").read_text(encoding="utf-8")
    assert text.startswith("(footprint") and parse(text)[1] == "SOT-223-3_L6.5-W3.4-P2.30-LS7.0-BR"


def test_upgrade_creates_output_folder(tmp_path, monkeypatch):
    # kicad-cli "Unable to save library" when the output folder does not exist yet.
    monkeypatch.setattr(kicad, "find_kicad_cli", lambda: Path("kicad-cli.exe"))
    seen = []

    def run(cmd, **kw):
        seen.append(Path(cmd[5]).parent.is_dir())
        return subprocess.CompletedProcess(cmd, 0, "", "")
    kicad.upgrade("sym", tmp_path / "a.kicad_sym", tmp_path / "up" / "a.kicad_sym", run=run)
    assert seen == [True]

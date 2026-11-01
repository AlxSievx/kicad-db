import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from conftest import REPO
from fakes import rec
from libkit import add as addmod
from libkit.add import apply, load_plan, prepare
from libkit.check import check
from libkit.datasheet import Result
from libkit.importer import fetch_easyeda
from libkit.jlc import parse_record
from libkit.parts import declare_family, load_parts
from libkit.schema import load_schema
from libkit.sexpr import find_all, parse
from test_importer import fake_run, fake_upgrade

ALIASES = {"AMS1117-3.3": "C6186"}
IC = dict(category="ics_power", family="Package_TO_SOT", fp_name="SOT-223-3_TabPin2")


def resolve(ref, stock=None):
    code = ALIASES.get(ref, ref)
    part = parse_record(rec(code))
    if stock is not None:
        part.stock = stock
    return part


def fetch(lcsc, workdir):
    return fetch_easyeda(lcsc, workdir, run=fake_run(), upgrade=fake_upgrade)


def lang(part):
    return Result("en")


SHARE = Path(__file__).parent / "fixtures" / "share"  # stock footprints without 3D models


def prep(root, ref, **kw):
    kw.setdefault("resolve", resolve)
    kw.setdefault("kicad_share_dir", SHARE)
    kw.setdefault("fetch", fetch)
    kw.setdefault("lang", lang)
    kw.setdefault("klc", False)
    return prepare(root, ref, **kw)


@pytest.fixture
def lib(minilib):
    """minilib plus the real base symbols (L, FerriteBead) and the 0805 inductor footprint."""
    shutil.copy(REPO / "src" / "symbols" / "passives.kicad_sym", minilib / "src" / "symbols" / "passives.kicad_sym")
    shutil.copy(REPO / "src" / "symbols" / "discretes.kicad_sym", minilib / "src" / "symbols")
    shutil.copy(REPO / "footprints" / "LIB_Passives_SMD.pretty" / "L_0805_2012Metric.kicad_mod",
                minilib / "footprints" / "LIB_Passives_SMD.pretty")
    shutil.copy(REPO / "3dmodels" / "LIB_Passives_SMD.3dshapes" / "L_0805_2012Metric.step",
                minilib / "3dmodels" / "LIB_Passives_SMD.3dshapes")
    from libkit.build import build
    build(minilib)
    return minilib


def snapshot(root: Path) -> dict[str, bytes]:
    return {f.relative_to(root).as_posix(): f.read_bytes() for f in sorted(root.rglob("*"))
            if f.is_file() and ".libkit" not in f.parts}


def test_add_chip_inductor(lib):
    before = snapshot(lib)
    p = prep(lib, "C1046")
    assert p.entry["name"] == "L_10u_0805_15mA" and p.category == "inductors"
    assert p.files == {} and p.symbol is None and p.new_family is None
    assert p.entry["datasheet_lang"] == "en"
    assert snapshot(lib) == before
    assert (lib / ".libkit" / "add" / "C1046" / "plan.json").exists()


def test_add_chip_bead(lib):
    p = prep(lib, "C1015")
    assert p.entry["name"] == "FB_100R_0805_800mA" and p.entry["symbol"] == "FerriteBead"


def test_add_chip_passive_rejects_overrides(lib):
    with pytest.raises(ValueError, match="chip"):
        prep(lib, "C1046", footprint="easyeda")


def test_add_chip_passive_needs_footprint_in_library(minilib):
    with pytest.raises(ValueError, match="L_0805_2012Metric"):
        prep(minilib, "C1046")


def test_add_ic_easyeda(lib):
    before = snapshot(lib)
    p = prep(lib, "C6186", **IC)
    assert p.entry["name"] == "AMS1117-3.3" and p.entry["symbol"] == "AMS1117-3.3"
    assert p.entry["footprint"] == "LIB_Package_TO_SOT:SOT-223-3_TabPin2"
    assert p.entry["value"] == "AMS1117-3.3" and not p.entry["description"].endswith("ROHS")
    assert set(p.files) == {"footprints/LIB_Package_TO_SOT.pretty/SOT-223-3_TabPin2.kicad_mod",
                            "3dmodels/LIB_Package_TO_SOT.3dshapes/SOT-223-3_TabPin2.step"}
    assert p.new_family == "Package_TO_SOT"
    assert '(symbol "AMS1117-3.3"' in p.symbol
    assert "(" not in p.entry["manufacturer"]
    assert any("not in manufacturers" in w for w in p.warnings)
    fp_text = (addmod.stage_dir(lib, "C6186") / "files" / "footprints" / "LIB_Package_TO_SOT.pretty"
               / "SOT-223-3_TabPin2.kicad_mod").read_text(encoding="utf-8")
    assert "https://" in fp_text  # KLC F9.1: a URL in the footprint description
    assert snapshot(lib) == before


def test_add_power_inductor_easyeda_footprint(lib):
    p = prep(lib, "C408412", footprint="easyeda", family="Inductor_SMD", fp_name="L_Sunlord_MWSA0503S")
    assert p.entry["name"] == "MWSA0503S-100MT" and p.entry["symbol"] == "L" and p.symbol is None
    assert p.entry["footprint"] == "LIB_Inductor_SMD:L_Sunlord_MWSA0503S"
    assert p.entry["value"] == "10uH" and p.category == "inductors"


def test_add_requires_category(lib):
    with pytest.raises(ValueError, match="--category"):
        prep(lib, "C6186", family="Package_TO_SOT")


def test_add_requires_family_for_new_footprint(lib):
    with pytest.raises(ValueError, match="--family"):
        prep(lib, "C6186", category="ics_power")


def test_add_bad_fp_name(lib):
    with pytest.raises(ValueError, match="fp-name"):
        prep(lib, "C6186", **{**IC, "fp_name": "SOT 223/x"})


def test_add_refuses_existing(lib):  # Review Focus 2
    with pytest.raises(ValueError, match="C_100n_0402_16V_X7R"):
        prep(lib, "C1525")


def test_add_refuses_existing_deprecated_name(lib):  # Review Focus 2
    from libkit.parts import write_category
    s = load_schema(lib)
    caps = [p.data for p in load_parts(lib, s) if p.category == "capacitors"]
    write_category(lib, "capacitors", caps + [{**caps[0], "name": "AMS1117-3.3", "lcsc": "C1",
                                                "status": "deprecated"}])
    with pytest.raises(ValueError, match="AMS1117-3.3.*already"):
        prep(lib, "C6186", **IC)


def test_add_refuses_no_stock(lib):
    with pytest.raises(ValueError, match="stock"):
        prep(lib, "C1046", resolve=lambda ref: resolve(ref, stock=0))
    p = prep(lib, "C1046", resolve=lambda ref: resolve(ref, stock=50))
    assert "low stock 50" in p.warnings


def test_add_derived_from_existing_symbol(lib):
    p = prep(lib, "C6186", category="ics_power", symbol="R", footprint="LIB_Passives_SMD:R_0402_1005Metric")
    assert p.entry["symbol"] == "R" and p.symbol is None and p.files == {} and p.new_family is None


def test_add_unknown_symbol(lib):
    with pytest.raises(ValueError, match="NOPE"):
        prep(lib, "C6186", category="ics_power", symbol="NOPE", footprint="LIB_Passives_SMD:R_0402_1005Metric")


def test_add_reuses_existing_footprint(lib):
    p = prep(lib, "C6186", **IC)
    apply(lib, load_plan(lib, "C6186", p.options))
    q = prep(lib, "C408412", footprint="easyeda", family="Package_TO_SOT", fp_name="SOT-223-3_TabPin2")
    assert q.files == {} and any("reusing existing footprint" in n for n in q.notes)


def test_declare_family_keeps_comments(minilib):
    text = (minilib / "schema" / "library.yaml").read_text(encoding="utf-8")
    declare_family(minilib, "Package_TO_SOT")
    after = (minilib / "schema" / "library.yaml").read_text(encoding="utf-8")
    assert "Package_TO_SOT" in load_schema(minilib).families
    assert after.count("#") == text.count("#")
    declare_family(minilib, "Package_TO_SOT")  # no-op the second time
    assert (minilib / "schema" / "library.yaml").read_text(encoding="utf-8") == after


def test_write_applies_plan(lib):
    p = prep(lib, "C6186", **IC)
    written = apply(lib, load_plan(lib, "C6186", p.options))
    assert "Package_TO_SOT" in load_schema(lib).families
    assert (lib / "footprints" / "LIB_Package_TO_SOT.pretty" / "SOT-223-3_TabPin2.kicad_mod").exists()
    assert (lib / "3dmodels" / "LIB_Package_TO_SOT.3dshapes" / "SOT-223-3_TabPin2.step").exists()
    src = parse((lib / "src" / "symbols" / "ics_power.kicad_sym").read_text(encoding="utf-8"))
    assert [str(s[1]) for s in find_all(src, "symbol")] == ["AMS1117-3.3"]
    assert "AMS1117-3.3" in {p.name for p in load_parts(lib, load_schema(lib))}
    assert [i for i in check(lib, klc=False) if i.severity == "error"] == []
    assert lib / "parts" / "ics_power.yaml" in written


def test_write_chip_inductor(lib):
    p = prep(lib, "C1046")
    apply(lib, load_plan(lib, "C1046", p.options))
    assert "L_10u_0805_15mA" in {p.name for p in load_parts(lib, load_schema(lib))}
    assert [i for i in check(lib, klc=False) if i.severity == "error"] == []


def test_load_plan_refuses_changed_options(lib):
    p = prep(lib, "C6186", **IC)
    with pytest.raises(ValueError, match="options"):
        load_plan(lib, "C6186", {**p.options, "fp_name": "OTHER"})


def test_load_plan_refuses_old_plan(lib):
    p = prep(lib, "C6186", **IC)
    f = addmod.stage_dir(lib, "C6186") / "plan.json"
    data = json.loads(f.read_text(encoding="utf-8"))
    data["created"] = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
    f.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="older than"):
        load_plan(lib, "C6186", p.options)


def test_load_plan_refuses_missing(lib):
    with pytest.raises(ValueError, match="dry run"):
        load_plan(lib, "C6186", {})


def test_load_plan_refuses_when_added_meanwhile(lib):
    p = prep(lib, "C6186", **IC)
    apply(lib, load_plan(lib, "C6186", p.options))
    with pytest.raises(ValueError, match="already in the library"):
        load_plan(lib, "C6186", p.options)


def test_apply_rolls_back(lib, monkeypatch):  # Review Focus 5
    p = prep(lib, "C6186", **IC)
    plan = load_plan(lib, "C6186", p.options)
    before = snapshot(lib)

    def boom(root):
        raise RuntimeError("build failed")
    monkeypatch.setattr(addmod, "build", boom)
    with pytest.raises(RuntimeError, match="build failed"):
        apply(lib, plan)
    assert snapshot(lib) == before
    assert not (lib / "footprints" / "LIB_Package_TO_SOT.pretty").exists()
    assert not (lib / "3dmodels" / "LIB_Package_TO_SOT.3dshapes").exists()


def test_cli_dry_run_and_write(lib, monkeypatch, capsys):
    from libkit import __main__ as cli
    monkeypatch.chdir(lib)
    monkeypatch.setattr(addmod.jlc, "resolve", resolve)
    monkeypatch.setattr(addmod.importer, "fetch_easyeda", fetch)
    monkeypatch.setattr(addmod.Checker, "for_part", lambda self, part: Result("en"))
    args = ["add", "C6186", "--category", "ics_power", "--family", "Package_TO_SOT",
            "--fp-name", "SOT-223-3_TabPin2", "--no-klc"]
    assert cli.main(args) == 0
    out = capsys.readouterr().out
    assert "name: AMS1117-3.3" in out and "dry run" in out and "pinout vs datasheet" in out
    assert cli.main(args + ["--write"]) == 0
    assert "added AMS1117-3.3" in capsys.readouterr().out
    assert cli.main(["add", "C6186", "--category", "ics_power", "--write"]) == 1  # other options


@pytest.mark.kicad
def test_add_ic_klc_clean_footprint(lib):
    from libkit.klc import klc_dir
    if not (klc_dir(REPO) / "klc-check").exists():
        pytest.skip("KLC checker not installed")
    shutil.copytree(klc_dir(REPO), klc_dir(lib))
    p = prep(lib, "C6186", **{**IC, "klc": True})
    for rule in ("F5.1", "F5.2", "F5.3", "F6.2", "F6.3", "F9.1"):
        assert not [i for i in p.klc if f"KLC {rule}" in i], p.klc


def test_footprint_tags_have_no_commas(lib):
    # KLC F9.1: JLC packages like "SMD,5.4x5.2mm" must not put a comma into the tags.
    prep(lib, "C408412", footprint="easyeda", family="Inductor_SMD", fp_name="L_Sunlord_MWSA0503S")
    fp = parse((addmod.stage_dir(lib, "C408412") / "files" / "footprints" / "LIB_Inductor_SMD.pretty"
                / "L_Sunlord_MWSA0503S.kicad_mod").read_text(encoding="utf-8"))
    from libkit.sexpr import find
    assert "," not in str(find(fp, "tags")[1])


def test_description_cleaned(lib):
    p = prep(lib, "C6186", **IC)
    d = p.entry["description"]
    assert "℃" not in d and "°C" in d and "、" not in d


def test_add_non_chip_resistor_uses_passive_entry(lib):  # final review I1
    def res2512(ref):
        p = parse_record(rec("C25744"))
        p.package, p.lcsc = "2512", "C25745"  # C25744 itself is in minilib already
        return p
    p = prep(lib, "C25745", resolve=res2512, category="resistors",
             footprint="LIB_Passives_SMD:R_0402_1005Metric")
    assert p.entry["symbol"] == "R" and p.entry["name"] == "R_10k_2512_1pct"  # pattern names for any R/C package
    assert p.entry["tolerance"] == "±1%" and p.entry["power"]
    apply(lib, load_plan(lib, "C25745", p.options))
    assert [i for i in check(lib, klc=False) if i.severity == "error"] == []


def test_add_refuses_entry_that_would_not_build(lib):  # final review I1
    with pytest.raises(ValueError, match="tolerance"):
        prep(lib, "C6186", category="resistors", symbol="R", footprint="LIB_Passives_SMD:R_0402_1005Metric")


SOD123 = dict(footprint="stock:Diode_SMD:D_SOD-123", family="Diode_SMD")
SOT23 = dict(footprint="stock:Package_TO_SOT_SMD:SOT-23", family="Package_TO_SOT_SMD")
E2K_FP = dict(footprint="easyeda", family="Package_TO_SOT", fp_name="SOT-223-3_TabPin2")  # 4 pads


def test_add_diode_uses_base(lib):
    p = prep(lib, "C81598", **SOD123)
    assert p.category == "diodes" and p.entry["symbol"] == "D" and p.symbol is None
    assert p.entry["vr"] == "75V" and p.entry["name"] == "1N4148W"
    assert any("cathode" in n for n in p.notes)


def test_add_mosfet_uses_base(lib):
    p = prep(lib, "C20917", **SOT23)
    assert p.category == "transistors" and p.entry["symbol"] == "Q_NMOS_GSD" and p.entry["type"] == "N-MOSFET"


def test_add_dual_diode_keeps_easyeda(lib):  # Review Focus 4
    p = prep(lib, "C8592", **E2K_FP)
    assert p.category == "diodes" and p.symbol is not None
    assert any(n.startswith("no base symbol") for n in p.notes)


def test_add_base_pad_mismatch_falls_back(lib):
    p = prep(lib, "C81598", **E2K_FP)
    assert p.symbol is not None and p.entry["symbol"] == "1N4148W"
    assert any("does not fit pads 1, 2, 3, 4" in n for n in p.notes)


def test_add_explicit_symbol_wins(lib):
    p = prep(lib, "C81598", symbol="D_Schottky", **SOD123)
    assert p.entry["symbol"] == "D_Schottky"


def test_add_refuses_pin_without_pad(lib):
    with pytest.raises(ValueError, match=r"pin\(s\) 3"):
        prep(lib, "C81598", symbol="Q_NMOS_GSD", **SOD123)


def test_write_diode_builds_and_checks(lib):
    p = prep(lib, "C81598", **SOD123)
    apply(lib, load_plan(lib, "C81598", p.options))
    text = (lib / "symbols" / "LIB_Diodes.kicad_sym").read_text(encoding="utf-8")
    assert '(extends "D")' in text
    assert [i for i in check(lib, klc=False) if i.severity == "error"] == []

import json

import pytest
import re
from pathlib import Path

from libkit.build import build
from libkit.review import REVIEW_DIR, library_hash, review_data

PAGE = Path(__file__).resolve().parents[1] / "tools" / "libkit" / "review_page.html"


def load_js(path: Path, var: str) -> dict:
    text = path.read_text(encoding="utf-8")
    prefix = f"window.{var} = "
    assert text.startswith(prefix) and text.rstrip().endswith(";")
    return json.loads(text[len(prefix):].rstrip().rstrip(";"))


def edit(root, old, new, fname="resistors.yaml"):
    f = root / "parts" / fname
    text = f.read_text(encoding="utf-8")
    assert old in text
    f.write_text(text.replace(old, new, 1), encoding="utf-8")


def test_review_data_parts(minilib):
    d = review_data(minilib)
    by = {p["name"]: p for p in d["parts"]}
    r = by["R_10k_0402_1pct"]
    assert r["params"] == [["Tolerance", "±1%"], ["Power", "62.5mW"]]
    assert r["stock_low"] == 1000 and r["lib"] == "LIB_Resistors" and r["category"] == "resistors"
    assert r["mpn"] == "0402WGF1002TCE" and r["lcsc"] == "C25744" and r["jlc_type"] == "Basic"
    assert isinstance(r["stock"], int) or r["stock"] is None
    assert "10k" in r["keywords"] and r["description"]
    assert ["MPN", "0402WGF1002TCE"] in r["fields"]
    assert r["sym_svgs"] == [] and r["fp_svg"] is None


def test_review_data_categories(minilib):
    d = review_data(minilib)
    cats = {c["key"]: c for c in d["categories"]}
    assert set(cats) == {p["category"] for p in d["parts"]}
    assert cats["resistors"]["count"] == sum(p["category"] == "resistors" for p in d["parts"])
    assert cats["resistors"]["title"] == "Resistors"


def test_build_writes_page(minilib):
    build(minilib)
    out = minilib / REVIEW_DIR
    assert (out / "index.html").read_text(encoding="utf-8") == PAGE.read_text(encoding="utf-8")
    d = load_js(out / "data.js", "LIB_DATA")
    assert d["hash"] == library_hash(minilib) and d["previews"] is False


def test_data_js_escapes_markup(minilib):  # Review Focus 1
    evil = "</script><img src=x onerror=alert(1)> \"q\""
    edit(minilib, "    tolerance: ±1%\n", f"    tolerance: ±1%\n    tempco: '{evil}'\n")
    build(minilib)
    text = (minilib / REVIEW_DIR / "data.js").read_text(encoding="utf-8")
    assert "</script" not in text and "<img" not in text and not re.search(r"[^\x00-\x7f]", text)
    d = load_js(minilib / REVIEW_DIR / "data.js", "LIB_DATA")
    assert any(["Tempco", evil] in p["params"] for p in d["parts"])


def test_page_is_offline():
    text = PAGE.read_text(encoding="utf-8")
    assert not re.search(r"""(src|href)\s*=\s*["']https?:""", text)
    assert "@import" not in text and "fetch(" not in text and "innerHTML" not in text
    assert '<script src="data.js">' in text and '<script src="check.js">' in text


def test_library_hash_changes_with_data(minilib):
    h = library_hash(minilib)
    build(minilib)
    assert library_hash(minilib) == h
    edit(minilib, "power: 62.5mW", "power: 100mW")
    assert library_hash(minilib) != h


def test_deprecated_part_included(minilib):
    edit(minilib, "    status: active\n", "    status: deprecated\n")
    p = next(p for p in review_data(minilib)["parts"] if p["name"] == "R_10k_0402_1pct")
    assert p["status"] == "deprecated" and p["keywords"] == ""


def test_issues_per_part(minilib):
    edit(minilib, "    status: active\n", "    status: active\n    stock_checked: soon\n")
    p = next(p for p in review_data(minilib)["parts"] if p["name"] == "R_10k_0402_1pct")
    assert any(i["severity"] == "error" for i in p["issues"])


def fake_kicad(calls, fail=()):
    """Stands in for kicad-cli sym/fp export svg; records (kind, source name)."""
    import subprocess
    from libkit.sexpr import find_all, parse

    def run(cmd, **kw):
        kind, src, out = cmd[1], Path(cmd[4]), Path(cmd[cmd.index("-o") + 1])
        calls.append((kind, src.name))
        if src.stem in fail or src.name in fail:
            return subprocess.CompletedProcess(cmd, 1, "", "Error: boom\n")
        assert out.is_dir(), "kicad-cli fp export needs an existing output folder"
        if kind == "sym":
            for s in find_all(parse(src.read_text(encoding="utf-8")), "symbol"):
                (out / f"{s[1]}_unit1.svg").write_text("<svg/>", encoding="utf-8")
        else:
            for f in src.glob("*.kicad_mod"):
                (out / f"{f.stem}.svg").write_text("<svg/>", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, "", "")
    return run


def test_previews_cached(minilib):
    from libkit.review import write_review
    build(minilib)
    calls = []
    write_review(minilib, previews=True, run=fake_kicad(calls))
    assert ("sym", "LIB_Resistors.kicad_sym") in calls and ("fp", "LIB_Passives_SMD.pretty") in calls
    d = load_js(minilib / REVIEW_DIR / "data.js", "LIB_DATA")
    r = next(p for p in d["parts"] if p["name"] == "R_10k_0402_1pct")
    assert r["sym_svgs"] == ["svg/sym/LIB_Resistors/R_10k_0402_1pct_unit1.svg"]
    assert r["fp_svg"] == "svg/fp/LIB_Passives_SMD/R_0402_1005Metric.svg"
    assert (minilib / REVIEW_DIR / r["fp_svg"]).exists()
    calls.clear()
    write_review(minilib, previews=True, run=fake_kicad(calls))
    assert calls == []
    edit(minilib, "power: 62.5mW", "power: 100mW")
    build(minilib)
    write_review(minilib, previews=True, run=fake_kicad(calls))
    assert calls == [("sym", "LIB_Resistors.kicad_sym")]


def test_render_failure_is_a_note(minilib):  # Review Focus 2
    from libkit.review import write_review
    build(minilib)
    write_review(minilib, previews=True, run=fake_kicad([], fail={"LIB_Capacitors"}))
    d = load_js(minilib / REVIEW_DIR / "data.js", "LIB_DATA")
    assert any("LIB_Capacitors" in n and "boom" in n for n in d["notes"])
    caps = [p for p in d["parts"] if p["category"] == "capacitors"]
    assert caps and all(p["sym_svgs"] == [] for p in caps)
    assert all(p["sym_svgs"] for p in d["parts"] if p["category"] == "resistors")
    calls = []  # a failed library is tried again next time
    write_review(minilib, previews=True, run=fake_kicad(calls))
    assert calls == [("sym", "LIB_Capacitors.kicad_sym")]


def test_build_without_cli(minilib, monkeypatch):  # Review Focus 2
    from libkit import kicad
    monkeypatch.delenv("LIBKIT_PREVIEWS")
    monkeypatch.setattr(kicad, "find_kicad_cli", lambda: None)
    build(minilib)
    d = load_js(minilib / REVIEW_DIR / "data.js", "LIB_DATA")
    assert d["previews"] is False and any("kicad-cli not found" in n for n in d["notes"])


def test_removed_library_previews_dropped(minilib):
    from libkit.review import write_review
    build(minilib)
    write_review(minilib, previews=True, run=fake_kicad([]))
    stale = minilib / REVIEW_DIR / "svg" / "fp" / "LIB_Gone"
    stale.mkdir(parents=True)
    write_review(minilib, previews=True, run=fake_kicad([]))
    assert not stale.exists()


@pytest.mark.kicad
def test_render_real(minilib):
    from libkit.kicad import find_kicad_cli
    from libkit.review import write_review
    if find_kicad_cli() is None:
        pytest.skip("kicad-cli not installed")
    build(minilib)
    write_review(minilib, previews=True)
    d = load_js(minilib / REVIEW_DIR / "data.js", "LIB_DATA")
    r = next(p for p in d["parts"] if p["name"] == "R_10k_0402_1pct")
    assert r["sym_svgs"] == ["svg/sym/LIB_Resistors/R_10k_0402_1pct_unit1.svg"]
    for rel in r["sym_svgs"] + [r["fp_svg"]]:
        assert (minilib / REVIEW_DIR / rel).read_text(encoding="utf-8").lstrip().startswith("<?xml")


def _assign(root, *issues):
    from libkit.parts import Issue
    from libkit.review import assign_issues
    return assign_issues([Issue(*i) for i in issues], root)


def test_assign_by_symbol_item(minilib):
    per, lib = _assign(minilib, ("error", "LIB_Resistors:R_10k_0402_1pct", "KLC S3.3: x"))
    assert list(per) == ["R_10k_0402_1pct"] and lib == []
    assert per["R_10k_0402_1pct"] == [{"severity": "error", "message": "KLC S3.3: x"}]


def test_assign_part_name(minilib):
    per, _ = _assign(minilib, ("warning", "R_10k_0402_1pct", "manufacturer"))
    assert list(per) == ["R_10k_0402_1pct"]


def test_assign_base_symbol_to_users(minilib):
    per, _ = _assign(minilib, ("warning", "LIB_Resistors:R", "KLC S4.1: x"))
    d = review_data(minilib)
    assert set(per) == {p["name"] for p in d["parts"] if p["symbol"] == "R"} and per


def test_assign_footprint_to_users(minilib):  # KLC footprint items are bare names
    per, _ = _assign(minilib, ("error", "R_0402_1005Metric", "KLC F5.1: x"))
    d = review_data(minilib)
    assert set(per) == {p["name"] for p in d["parts"] if p["footprint"] == "LIB_Passives_SMD:R_0402_1005Metric"}


def test_assign_unknown_is_library_wide(minilib):
    per, lib = _assign(minilib, ("error", None, "stale: x — run build"), ("error", "Nope:Nope", "y"))
    assert per == {} and [i["message"] for i in lib] == ["stale: x — run build", "Nope:Nope: y"]


def _check_cli(root, monkeypatch):
    from libkit import __main__ as cli
    monkeypatch.chdir(root)
    return cli.main(["check", "--no-klc"])


def test_check_js_hash_matches_data(minilib, monkeypatch):  # Review Focus 3
    build(minilib)
    assert _check_cli(minilib, monkeypatch) == 0
    c = load_js(minilib / REVIEW_DIR / "check.js", "LIB_CHECK")
    d = load_js(minilib / REVIEW_DIR / "data.js", "LIB_DATA")
    assert c["hash"] == d["hash"] and c["klc"] is False and c["errors"] == 0


def test_check_js_stale_after_change(minilib, monkeypatch):  # Review Focus 3
    build(minilib)
    _check_cli(minilib, monkeypatch)
    edit(minilib, "power: 62.5mW", "power: 100mW")
    build(minilib)
    c = load_js(minilib / REVIEW_DIR / "check.js", "LIB_CHECK")
    d = load_js(minilib / REVIEW_DIR / "data.js", "LIB_DATA")
    assert c["hash"] != d["hash"]


def test_check_js_on_broken_yaml(minilib, monkeypatch):
    build(minilib)
    (minilib / "parts" / "resistors.yaml").write_text("parts: [oops", encoding="utf-8")
    assert _check_cli(minilib, monkeypatch) == 1
    c = load_js(minilib / REVIEW_DIR / "check.js", "LIB_CHECK")
    assert c["hash"] == "" and c["errors"] >= 1

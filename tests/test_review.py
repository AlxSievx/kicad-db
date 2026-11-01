import json
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

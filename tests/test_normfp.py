import math
from pathlib import Path

import pytest

from libkit.normfp import normalize_footprint
from libkit.sexpr import dumps, find, find_all, parse

FIX = Path(__file__).parent / "fixtures" / "easyeda"
SOT = FIX / "C6186" / "up" / "E2K.pretty" / "SOT-223-3_L6.5-W3.4-P2.30-LS7.0-BR.kicad_mod"
NAME = "SOT-223-3_TabPin2"
LIB = "LIB_Package_TO_SOT"


def load(path: Path) -> list:
    return parse(path.read_text(encoding="utf-8"))


def norm(path=SOT, **kw):
    kw.setdefault("name", NAME)
    kw.setdefault("lib", LIB)
    kw.setdefault("model", f"{NAME}.step")
    kw.setdefault("description", "SOT-223 LDO, https://www.lcsc.com/datasheet/C6186.pdf")
    kw.setdefault("tags", "SOT-223")
    return normalize_footprint(load(path), **kw)


def layer(node) -> str:
    n = find(node, "layer")
    return str(n[1]) if n else ""


def width(node) -> float:
    return float(find(find(node, "stroke"), "width")[1])


def graphics(fp, lay):
    return [c for c in fp if isinstance(c, list) and c and str(c[0]).startswith("fp_")
            and str(c[0]) != "fp_text" and layer(c) == lay]


def xy(node, head):
    n = find(node, head)
    return float(n[1]), float(n[2])


def test_name_descr_tags_properties():
    fp, _ = norm()
    assert fp[1] == NAME
    assert str(find(fp, "descr")[1]).startswith("SOT-223 LDO") and str(find(fp, "tags")[1]) == "SOT-223"
    assert str(find(fp, "generator")[1]) == "libkit"
    props = {str(p[1]): p for p in find_all(fp, "property")}
    assert set(props) == {"Reference", "Value", "Datasheet", "Description"}
    assert str(props["Value"][2]) == NAME and layer(props["Value"]) == "F.Fab"
    assert layer(props["Reference"]) == "F.SilkS"
    font = find(find(props["Reference"], "effects"), "font")
    assert [str(x) for x in find(font, "size")[1:]] == ["1", "1"] and str(find(font, "thickness")[1]) == "0.15"


def test_layers_and_widths():
    fp, notes = norm()
    assert not any(layer(c) in ("Cmts.User", "Dwgs.User") for c in fp if isinstance(c, list))
    silk = graphics(fp, "F.SilkS")
    assert silk and all(width(g) == 0.12 for g in silk)
    fab = graphics(fp, "F.Fab")
    assert fab and all(width(g) == 0.10 for g in fab)
    assert any("fab outline copied" in n for n in notes)


def test_fab_reference_text():
    fp, _ = norm()
    refs = [t for t in find_all(fp, "fp_text") if str(t[1]) == "user" and str(t[2]) == "${REFERENCE}"]
    assert len(refs) == 1 and layer(refs[0]) == "F.Fab"
    size = find(find(find(refs[0], "effects"), "font"), "size")
    # shorter fab side 2.94 mm → 0.4 × 2.94 = 1.18 → clamped to 1.0
    assert [float(x) for x in size[1:]] == [1.0, 1.0]


def test_courtyard_covers_pads():
    fp, _ = norm()
    crt = graphics(fp, "F.CrtYd")
    assert len(crt) == 1 and str(crt[0][0]) == "fp_rect" and width(crt[0]) == 0.05
    (x1, y1), (x2, y2) = xy(crt[0], "start"), xy(crt[0], "end")
    # pads span x -4.14..4.22 (centre 0.04, moved to 0 → -4.18..4.18); the fab outline
    # (from silk) spans y ±3.33; plus 0.25 mm
    assert (x1, y1, x2, y2) == (-4.43, -3.58, 4.43, 3.58)
    for v in (x1, y1, x2, y2):
        assert abs(v * 100 - round(v * 100)) < 1e-9


def test_pads_roundrect():
    fp, _ = norm()
    pads = {str(p[1]): p for p in find_all(fp, "pad")}
    assert all(str(p[3]) == "roundrect" for p in pads.values())
    assert str(find(pads["1"], "roundrect_rratio")[1]) == "0.2273"   # 0.25 / 1.1
    assert str(find(pads["4"], "roundrect_rratio")[1]) == "0.1068"   # 0.25 / 2.34


def test_model_path_and_rotation():
    fp, _ = norm()
    models = find_all(fp, "model")
    assert len(models) == 1
    assert str(models[0][1]) == f"${{LIB_DIR}}/3dmodels/{LIB}.3dshapes/{NAME}.step"
    assert [str(x) for x in find(find(models[0], "rotate"), "xyz")[1:]] == ["0", "0", "180"]


def test_small_anchor_offset_recentred():
    fp, notes = norm()
    pads = {str(p[1]): p for p in find_all(fp, "pad")}
    assert xy(pads["1"], "at") == (2.93, 2.3) and xy(pads["4"], "at") == (-3.01, 0)
    assert any("anchor moved" in n for n in notes)
    # the 3D model moves with the footprint (model offset: Y axis points up)
    assert [str(x) for x in find(find(find(fp, "model"), "offset"), "xyz")[1:]] == ["-0.04", "0", "0"]


def test_large_anchor_offset_kept(tmp_path):
    text = SOT.read_text(encoding="utf-8").replace("(at -2.97 0)", "(at -3.97 0)")
    path = tmp_path / "x.kicad_mod"
    path.write_text(text, encoding="utf-8")
    fp, notes = norm(path=path)
    assert xy({str(p[1]): p for p in find_all(fp, "pad")}["4"], "at") == (-3.97, 0)
    assert any("anchor" in n and "KLC F6.2" in n for n in notes)


def test_orientation_note():
    _, notes = norm()
    assert any(n.startswith("orientation") for n in notes)


def test_no_model():  # Review Focus 4
    fp, notes = norm(model=None)
    assert find_all(fp, "model") == []
    assert "no 3D model" in notes


def test_tht_pads_untouched():  # Review Focus 4
    fp, notes = norm(path=FIX / "tht.kicad_mod", name="TEST_THT", model=None)
    pads = {str(p[1]): p for p in find_all(fp, "pad")}
    assert [str(pads[n][3]) for n in "123"] == ["rect", "circle", "roundrect"]
    assert [str(x) for x in find(pads["1"], "layers")[1:]] == ["*.Cu", "*.Mask"]
    assert str(find(pads["3"], "roundrect_rratio")[1]) == "0.2"
    # the existing fab drawing is kept, nothing copied from silk
    assert not any("fab outline copied" in n for n in notes)
    assert len(graphics(fp, "F.Fab")) == 1
    assert not any(n.startswith("orientation") for n in notes)  # pin 1 is left of centre


def test_output_reparses():
    fp, _ = norm()
    assert parse(dumps(fp))[1] == NAME


@pytest.mark.kicad
def test_normalised_footprint_passes_klc(tmp_path):
    from libkit.klc import klc_dir, run_klc
    repo = Path(__file__).resolve().parents[1]
    if not (klc_dir(repo) / "klc-check").exists():
        pytest.skip("KLC checker not installed")
    fp, _ = norm()
    out = tmp_path / f"{LIB}.pretty" / f"{NAME}.kicad_mod"
    out.parent.mkdir()
    out.write_text(dumps(fp), encoding="utf-8")
    issues = [str(i) for i in run_klc(repo, [out])]
    for rule in ("F5.1", "F5.2", "F5.3", "F6.3", "F9.1"):
        assert not [i for i in issues if f"KLC {rule}" in i], issues


CUSTOM = """(footprint "CUSTOM"
	(version 20260206)
	(layer "F.Cu")
	(property "Reference" "REF**" (at 0 -2 0) (layer "F.SilkS"))
	(property "Value" "CUSTOM" (at 0 2 0) (layer "F.Fab"))
	(attr smd)
	(pad "1" smd custom (at -1 0) (size 0.2 0.2) (layers "F.Cu" "F.Mask" "F.Paste")
		(primitives (gr_poly (pts (xy -0.5 -0.5) (xy 0.5 -0.5) (xy 0.5 0.5) (xy -0.5 0.5)) (width 0) (fill yes))))
	(pad "2" smd custom (at 1.05 0) (size 0.2 0.2) (layers "F.Cu" "F.Mask" "F.Paste")
		(primitives (gr_poly (pts (xy -0.5 -0.5) (xy 2 -0.5) (xy 2 0.5) (xy -0.5 0.5)) (width 0) (fill yes))))
)
"""


def test_custom_pad_primitives_in_courtyard_and_not_moved(tmp_path):  # final review I2
    path = tmp_path / "c.kicad_mod"
    path.write_text(CUSTOM, encoding="utf-8")
    fp, notes = norm(path=path, name="CUSTOM", model=None)
    pads = {str(p[1]): p for p in find_all(fp, "pad")}
    # copper spans x -1.5 .. 3.05 → centre 0.775 > 0.1 mm: anchor kept, reported
    assert xy(pads["2"], "at") == (1.05, 0)
    assert any("anchor is" in n for n in notes)
    poly = find(find(pads["2"], "primitives"), "gr_poly")
    assert [str(x) for x in find_all(find(poly, "pts"), "xy")[1][1:]] == ["2", "-0.5"]
    crt = graphics(fp, "F.CrtYd")[0]
    assert xy(crt, "end")[0] >= 3.05 + 0.25 - 1e-9


def test_custom_pad_recentre_moves_anchor_only(tmp_path):  # final review I2
    path = tmp_path / "c.kicad_mod"
    path.write_text(CUSTOM.replace("(at 1.05 0)", "(at -1 0)").replace("(xy 2 -0.5) (xy 2 0.5)", "(xy 3.1 -0.5) (xy 3.1 0.5)")
                    .replace('(pad "1" smd custom (at -1 0)', '(pad "1" smd custom (at -1.5 0)'), encoding="utf-8")
    # copper: pad 1 -2.0..-1.0, pad 2 -1.5..2.1 → centre 0.05 → moved by -0.05
    fp, notes = norm(path=path, name="CUSTOM", model=None)
    pads = {str(p[1]): p for p in find_all(fp, "pad")}
    assert xy(pads["2"], "at") == (-1.05, 0)
    poly = find(find(pads["2"], "primitives"), "gr_poly")
    assert [str(x) for x in find_all(find(poly, "pts"), "xy")[1][1:]] == ["3.1", "-0.5"]

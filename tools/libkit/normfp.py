"""Normalise an imported footprint (KiCad 10 format) to the library style.

Input is a footprint as `kicad-cli fp upgrade` writes it from easyeda2kicad
output. The rules (values from KLC) are applied in a fixed order; what a
machine cannot decide comes back as notes for the human review.
"""

from __future__ import annotations

import copy
import math

from .sexpr import Sym, find, find_all

KEEP_PROPS = ("Reference", "Value", "Datasheet", "Description")
KEEP_LAYERS = {"F.SilkS", "B.SilkS", "F.Fab", "B.Fab", "F.CrtYd", "B.CrtYd"}
SILK_WIDTH = "0.12"
FAB_WIDTH = "0.1"
CRTYD_WIDTH = "0.05"
CRTYD_CLEARANCE = 0.25
GRID = 0.01
FAB_TEXT_MIN, FAB_TEXT_MAX = 0.5, 1.0
GRAPHICS = ("fp_line", "fp_rect", "fp_circle", "fp_arc", "fp_poly", "fp_curve")
FAB_FROM_SILK = ("fp_line", "fp_rect", "fp_arc", "fp_poly")
MAX_RECENTRE = 0.1  # mm: a larger anchor offset is reported, not moved (JLC places by the anchor)
POINT_HEADS = ("at", "start", "mid", "end", "center", "xy")


def _num(v: float) -> Sym:
    text = f"{round(v, 4):.4f}".rstrip("0").rstrip(".")
    return Sym("0" if text in ("-0", "") else text)


def _layer(node: list) -> str:
    n = find(node, "layer")
    return str(n[1]) if n else ""


def _is(node, *heads) -> bool:
    return isinstance(node, list) and bool(node) and str(node[0]) in heads


def _set_child(node: list, head: str, value: list) -> None:
    for i, c in enumerate(node):
        if _is(c, head):
            node[i] = value
            return
    node.append(value)


def _set_width(node: list, width: str) -> None:
    stroke = find(node, "stroke")
    if stroke is None:
        stroke = [Sym("stroke"), [Sym("width"), Sym(width)], [Sym("type"), Sym("solid")]]
        node.insert(len(node) - 1 if _is(node[-1], "uuid") else len(node), stroke)
    else:
        _set_child(stroke, "width", [Sym("width"), Sym(width)])


def _font(size: float, thickness: float) -> list:
    return [Sym("effects"), [Sym("font"), [Sym("size"), _num(size), _num(size)],
                             [Sym("thickness"), _num(thickness)]]]


# --- geometry ---------------------------------------------------------------

def _pt(node: list, head: str) -> tuple[float, float] | None:
    n = find(node, head)
    return (float(n[1]), float(n[2])) if n else None


def _graphic_points(g: list) -> list[tuple[float, float]]:
    """Extreme points of a footprint graphic (fp_*) or a custom-pad primitive (gr_*)."""
    head = "fp_" + str(g[0]).split("_", 1)[-1]
    if head == "fp_circle":
        (cx, cy), (ex, ey) = _pt(g, "center"), _pt(g, "end")
        r = math.hypot(ex - cx, ey - cy)
        return [(cx - r, cy - r), (cx + r, cy + r)]
    if head in ("fp_poly", "fp_curve"):
        pts = find(g, "pts")
        return [(float(p[1]), float(p[2])) for p in find_all(pts, "xy")] if pts else []
    return [p for p in (_pt(g, "start"), _pt(g, "mid"), _pt(g, "end")) if p]


def _pad_points(pad: list) -> list[tuple[float, float]]:
    """Extreme copper points of a pad, including a custom pad's primitives
    (pad-relative, rotated with the pad, widened by half their line width)."""
    at, size = find(pad, "at"), find(pad, "size")
    x, y = float(at[1]), float(at[2])
    rot = float(at[3]) if len(at) > 3 else 0.0
    w, h = float(size[1]), float(size[2])
    if rot % 180 == 90:
        w, h = h, w
    elif rot % 90:
        w = h = math.hypot(w, h)
    points = [(x - w / 2, y - h / 2), (x + w / 2, y + h / 2)]
    prims = find(pad, "primitives")
    if prims:
        c, s = math.cos(math.radians(rot)), math.sin(math.radians(rot))
        for g in prims:
            if not isinstance(g, list) or not g:
                continue
            half = float(find(g, "width")[1]) / 2 if find(g, "width") else 0.0
            for px, py in _graphic_points(g):
                rx, ry = x + px * c + py * s, y - px * s + py * c
                points += [(rx - half, ry - half), (rx + half, ry + half)]
    return points


def _bbox(points) -> tuple[float, float, float, float] | None:
    pts = list(points)
    if not pts:
        return None
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def _translate(node: list, dx: float, dy: float) -> None:
    """Move every coordinate in the tree by (dx, dy); 3D model offsets too
    (their Y axis points up). Coordinates inside `model` are left otherwise."""
    for c in node:
        if not isinstance(c, list) or not c:
            continue
        head = str(c[0])
        if head == "model":
            xyz = find(find(c, "offset") or [], "xyz")
            if xyz:
                xyz[1], xyz[2] = _num(float(xyz[1]) + dx), _num(float(xyz[2]) - dy)
            continue
        if head in POINT_HEADS and len(c) >= 3:
            c[1], c[2] = _num(float(c[1]) + dx), _num(float(c[2]) + dy)
            continue
        if head == "pad":  # only the pad position: primitives are pad-relative
            _translate([find(c, "at")], dx, dy)
            continue
        _translate(c, dx, dy)


def _out(v: float, up: bool) -> float:
    """Round to the courtyard grid, away from the part."""
    steps = v / GRID
    steps = math.ceil(steps - 1e-6) if up else math.floor(steps + 1e-6)
    return round(steps * GRID, 2)


# --- rules ------------------------------------------------------------------

def normalize_footprint(fp: list, *, name: str, lib: str, model: str | None, description: str,
                        tags: str) -> tuple[list, list[str]]:
    fp = copy.deepcopy(fp)
    notes: list[str] = []

    # 1. Name, generator, description, tags.
    fp[1] = name
    _set_child(fp, "generator", [Sym("generator"), "libkit"])
    head_end = next(i for i, c in enumerate(fp) if _is(c, "layer")) + 1
    for head, text in (("tags", tags), ("descr", description)):
        fp[:] = [c for c in fp if not _is(c, head)]
        fp.insert(head_end, [Sym(head), text])

    # 2. Properties.
    kept = []
    for c in fp:
        if _is(c, "property") and str(c[1]) not in KEEP_PROPS:
            continue
        if _is(c, "property") and str(c[1]) == "Value":
            c[2] = name
            _set_child(c, "layer", [Sym("layer"), "F.Fab"])
        if _is(c, "property") and str(c[1]) == "Reference":
            _set_child(c, "layer", [Sym("layer"), "F.SilkS"])
            _set_child(c, "effects", _font(1.0, 0.15))
        kept.append(c)
    fp[:] = kept

    # 3. Graphics: only silk, fab and courtyard layers; KLC widths.
    fp[:] = [c for c in fp if not (_is(c, *GRAPHICS) and _layer(c) not in KEEP_LAYERS)
             and not (_is(c, "fp_text") and _layer(c) not in KEEP_LAYERS)]
    graphics = [c for c in fp if _is(c, *GRAPHICS)]
    for g in graphics:
        if _layer(g).endswith("SilkS"):
            _set_width(g, SILK_WIDTH)
        elif _layer(g).endswith("Fab"):
            _set_width(g, FAB_WIDTH)

    # 3b. SMD anchor in the middle of the pads (KLC F6.2), when only slightly off.
    pads = find_all(fp, "pad")
    pad_box = _bbox(p for pad in pads for p in _pad_points(pad))
    attr = find(fp, "attr")
    if pad_box is not None and attr is not None and str(attr[1]) == "smd":
        cx, cy = round((pad_box[0] + pad_box[2]) / 2, 4), round((pad_box[1] + pad_box[3]) / 2, 4)
        if max(abs(cx), abs(cy)) > 0.001:
            if max(abs(cx), abs(cy)) <= MAX_RECENTRE:
                _translate(fp, -cx, -cy)
                notes.append(f"anchor moved by ({_num(-cx)}, {_num(-cy)}) mm to the middle of the pads (KLC F6.2)")
                pad_box = _bbox(p for pad in pads for p in _pad_points(pad))
            else:
                notes.append(f"anchor is ({cx:g}, {cy:g}) mm off the middle of the pads (KLC F6.2) — "
                             "kept, JLC places by the anchor; recentre or allow-list")

    # 4. Fab outline.
    fab = [g for g in graphics if _layer(g).endswith("Fab")]
    if not fab:
        for g in graphics:
            if _layer(g) == "F.SilkS" and _is(g, *FAB_FROM_SILK):
                f = copy.deepcopy(g)
                f[:] = [c for c in f if not _is(c, "uuid")]
                _set_child(f, "layer", [Sym("layer"), "F.Fab"])
                _set_width(f, FAB_WIDTH)
                fab.append(f)
        if fab:
            notes.append("fab outline copied from silkscreen — check against the package drawing")
        insert_at = max(i for i, c in enumerate(fp) if _is(c, *GRAPHICS)) + 1 if graphics else len(fp)
        fp[insert_at:insert_at] = fab

    # 5. ${REFERENCE} on F.Fab.
    fp[:] = [c for c in fp if not (_is(c, "fp_text") and str(c[1]) == "user" and str(c[2]) == "${REFERENCE}")]
    fab_box = _bbox(p for g in fab for p in _graphic_points(g))
    ref_box = fab_box or pad_box or (0.0, 0.0, 0.0, 0.0)
    shorter = min(ref_box[2] - ref_box[0], ref_box[3] - ref_box[1])
    size = round(min(FAB_TEXT_MAX, max(FAB_TEXT_MIN, 0.4 * shorter)), 2)
    cx, cy = (ref_box[0] + ref_box[2]) / 2, (ref_box[1] + ref_box[3]) / 2
    ref_text = [Sym("fp_text"), Sym("user"), "${REFERENCE}",
                [Sym("at"), _num(cx), _num(cy), Sym("0")], [Sym("layer"), "F.Fab"],
                _font(size, 0.15 * size)]
    first_pad = next((i for i, c in enumerate(fp) if _is(c, "pad")), len(fp))
    fp.insert(first_pad, ref_text)

    # 6. Courtyard.
    fp[:] = [c for c in fp if not (_is(c, *GRAPHICS) and _layer(c).endswith("CrtYd"))]
    box = _bbox([p for pad in pads for p in _pad_points(pad)] + [p for g in fab for p in _graphic_points(g)])
    if box is not None:
        x1, y1 = _out(box[0] - CRTYD_CLEARANCE, False), _out(box[1] - CRTYD_CLEARANCE, False)
        x2, y2 = _out(box[2] + CRTYD_CLEARANCE, True), _out(box[3] + CRTYD_CLEARANCE, True)
        crt = [Sym("fp_rect"), [Sym("start"), _num(x1), _num(y1)], [Sym("end"), _num(x2), _num(y2)],
               [Sym("stroke"), [Sym("width"), Sym(CRTYD_WIDTH)], [Sym("type"), Sym("solid")]],
               [Sym("fill"), Sym("no")], [Sym("layer"), "F.CrtYd"]]
        fp.insert(next(i for i, c in enumerate(fp) if _is(c, "fp_text") and str(c[2]) == "${REFERENCE}"), crt)

    # 7. SMD pads: rect → roundrect (radius 25 % of the shorter side, at most 0.25 mm).
    for pad in pads:
        if str(pad[2]) == "smd" and str(pad[3]) == "rect":
            size_node = find(pad, "size")
            shorter = min(float(size_node[1]), float(size_node[2]))
            pad[3] = Sym("roundrect")
            ratio = min(0.25, 0.25 / shorter) if shorter > 0 else 0.25
            layers_at = next(i for i, c in enumerate(pad) if _is(c, "layers"))
            pad.insert(layers_at + 1, [Sym("roundrect_rratio"), _num(ratio)])

    # 8. 3D model.
    models = [c for c in fp if _is(c, "model")]
    fp[:] = [c for c in fp if not _is(c, "model")]
    if model is None:
        notes.append("no 3D model")
    else:
        m = copy.deepcopy(models[0]) if models else [
            Sym("model"), "",
            [Sym("offset"), [Sym("xyz"), Sym("0"), Sym("0"), Sym("0")]],
            [Sym("scale"), [Sym("xyz"), Sym("1"), Sym("1"), Sym("1")]],
            [Sym("rotate"), [Sym("xyz"), Sym("0"), Sym("0"), Sym("0")]]]
        m[1] = f"${{LIB_DIR}}/3dmodels/{lib}.3dshapes/{model}"
        fp.append(m)

    # 9. Orientation (KLC: pin 1 top-left); kept, only reported.
    pin1 = next((p for p in pads if str(p[1]) == "1"), None)
    if pin1 is not None and pad_box is not None:
        x, y = float(find(pin1, "at")[1]), float(find(pin1, "at")[2])
        mx, my = (pad_box[0] + pad_box[2]) / 2, (pad_box[1] + pad_box[3]) / 2
        if x > mx + 1e-6 or (abs(x - mx) <= 1e-6 and y > my + 1e-6):
            notes.append("orientation: pin 1 is not top-left (EasyEDA/JLC orientation kept)")
    return fp, notes

"""The read-only review page (spec §6.9): build/review/index.html.

The page (review_page.html, copied as it is) reads data.js, written here by
`build`, and check.js, written by `libkit check`. Both set a global
(window.LIB_DATA, window.LIB_CHECK), so the page works from file:// with no
server and no fetch(). Preview SVGs live in build/review/svg/.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

from .parts import Issue, Part, load_parts, validate
from .pins import pin_pad_issues
from .schema import Schema, load_schema
from .sexpr import Sym, dumps, find, find_all, parse
from .stock import LOW_STOCK_OTHER, LOW_STOCK_PASSIVE
from .symgen import load_source_symbols, write_text
from .text import build_description, build_keywords

REVIEW_DIR = Path("build") / "review"
PAGE = Path(__file__).with_name("review_page.html")


def _canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=True, separators=(",", ":"))


def _hash(parts: list[Part]) -> str:
    rows = sorted(([p.name, p.category, p.data] for p in parts), key=lambda r: (r[0], r[1]))
    return hashlib.sha256(_canonical(rows).encode("ascii")).hexdigest()


def library_hash(root: Path) -> str:
    """A fingerprint of all part data; check.js is current when it matches data.js."""
    root = Path(root)
    return _hash(load_parts(root, load_schema(root)))


def js_assign(var: str, data: dict) -> str:
    """`window.<var> = <json>;` — ASCII only, and no "<" so nothing can close the script."""
    text = json.dumps(data, ensure_ascii=True, indent=None, separators=(",", ":")).replace("<", "\\u003c")
    return f"window.{var} = {text};\n"


def _issue(i: Issue) -> dict:
    return {"severity": i.severity, "message": i.message}


def _part_row(p: Part, schema: Schema, issues: list[Issue], svgs: dict) -> dict:
    cat = schema.categories[p.category]
    d = p.data
    labels = {f.key: f.label or f.key.replace("_", " ").capitalize() for f in schema.fields_for(cat)}
    stock = d.get("stock")
    return {
        "name": p.name,
        "category": p.category,
        "lib": cat.lib_name,
        "value": d.get("value", ""),
        "package": d.get("package", ""),
        "params": [[f.label or f.key, d[f.key]] for f in cat.fields if d.get(f.key)],
        "manufacturer": d.get("manufacturer", ""),
        "mpn": d.get("mpn", ""),
        "lcsc": d.get("lcsc", ""),
        "jlc_type": d.get("jlc_type", ""),
        "stock": int(stock) if stock and stock.isdigit() else None,
        "stock_low": LOW_STOCK_PASSIVE if cat.value_unit else LOW_STOCK_OTHER,
        "stock_checked": d.get("stock_checked", ""),
        "datasheet": d.get("datasheet", ""),
        "datasheet_lang": d.get("datasheet_lang", ""),
        "status": d.get("status", ""),
        "description": build_description(p, schema),
        "footprint": d.get("footprint", ""),
        "symbol": d.get("symbol", ""),
        "keywords": build_keywords(p, schema),
        "fields": [[labels[k], d[k]] for k in labels if d.get(k)] + [[k, v] for k, v in d.items() if k not in labels],
        "issues": [_issue(i) for i in issues],
        "sym_svgs": svgs.get(("sym", cat.lib_name, p.name), []),
        "fp_svg": svgs.get(("fp", d.get("footprint", "")), None),
    }


def review_data(root: Path, svgs: dict | None = None, notes: list[str] | None = None,
                previews: bool = False) -> dict:
    """Everything the page shows. `svgs` maps ("sym", lib, part) to a list of
    paths and ("fp", "<lib>:<name>") to a path, relative to build/review/."""
    root = Path(root)
    schema = load_schema(root)
    parts = load_parts(root, schema)
    issues = validate(parts, schema, root)
    try:
        issues += pin_pad_issues(parts, load_source_symbols(root), root)
    except (ValueError, KeyError) as e:
        issues.append(Issue("error", None, str(e)))
    by_part: dict[str, list[Issue]] = {}
    for i in issues:
        if i.part:
            by_part.setdefault(i.part, []).append(i)
    counts: dict[str, int] = {}
    for p in parts:
        counts[p.category] = counts.get(p.category, 0) + 1
    return {
        "hash": _hash(parts),
        "built": datetime.now().astimezone().isoformat(timespec="seconds"),
        "notes": list(notes or []) + [str(i) for i in issues if not i.part],
        "previews": previews,
        "categories": [{"key": c.key, "title": c.title, "lib": c.lib_name, "count": counts[c.key]}
                       for c in schema.categories.values() if c.key in counts],
        "parts": [_part_row(p, schema, by_part.get(p.name, []), svgs or {})
                  for p in sorted(parts, key=lambda p: (p.category, p.name))],
    }


def previews_wanted(previews: bool | None) -> tuple[bool, str]:
    """(render?, note when not)."""
    if previews is not None:
        return previews, "" if previews else "previews off"
    if os.environ.get("LIBKIT_PREVIEWS") == "0":
        return False, "previews off: LIBKIT_PREVIEWS=0"
    from .kicad import find_kicad_cli
    if find_kicad_cli() is None:
        return False, "previews off: kicad-cli not found"
    return True, ""


def assign_issues(issues: list[Issue], root: Path) -> tuple[dict[str, list[dict]], list[dict]]:
    """Check results per part name, and those that belong to no part.

    Issue.part may be a part name, "<Lib>:<Name>" (KLC symbols), a base
    symbol ("<Lib>:R": every part of that library deriving from R), or a
    footprint name (KLC footprints: every part using it)."""
    root = Path(root)
    try:
        schema = load_schema(root)
        parts = load_parts(root, schema)
    except (OSError, KeyError, TypeError, ValueError):  # broken data: everything is library-wide
        schema, parts = None, []
    names = {p.name for p in parts}
    lib_of = {p.name: schema.categories[p.category].lib_name for p in parts} if schema else {}
    per: dict[str, list[dict]] = {}
    library: list[dict] = []
    for i in issues:
        item = i.part or ""
        lib, sep, name = item.rpartition(":")
        if not sep:
            lib, name = "", item
        if item in names:
            hits = [item]
        elif name in names and (not lib or lib_of[name] == lib):
            hits = [name]
        else:
            hits = [p.name for p in parts if name and p.data.get("symbol") == name and p.name != name
                    and (not lib or lib_of[p.name] == lib)]
            if not hits:
                hits = [p.name for p in parts if name and p.data.get("footprint", "").partition(":")[2] == name
                        and (not lib or p.data["footprint"].partition(":")[0] == lib)]
        if hits:
            for h in hits:
                per.setdefault(h, []).append(_issue(i))
        else:
            library.append({"severity": i.severity, "message": f"{item}: {i.message}" if item else i.message})
    return per, library


def write_check_results(root: Path, issues: list[Issue], *, klc: bool) -> Path:
    """build/review/check.js for the page, stamped with the current library hash."""
    root = Path(root)
    try:
        digest = library_hash(root)
    except (OSError, KeyError, TypeError, ValueError):
        digest = ""
    per, library = assign_issues(issues, root)
    n_err = sum(i.severity == "error" for i in issues)
    data = {"hash": digest, "time": datetime.now().astimezone().isoformat(timespec="seconds"), "klc": klc,
            "errors": n_err, "warnings": len(issues) - n_err, "parts": per, "library": library}
    path = root / REVIEW_DIR / "check.js"
    write_text(path, js_assign("LIB_CHECK", data))
    return path


HASH_FILE = ".src-hash"
RENDER_VERSION = "2"  # bump when the render settings change: cached previews are redrawn
FP_LAYERS = "F.Cu,B.Cu,F.SilkS,F.Fab,F.CrtYd"  # with --sp: pads with their numbers on the fab layer


def _textless_copy(pretty: Path, tmp: Path) -> Path:
    """A copy of a footprint folder without texts: the Value (= footprint
    name) on F.Fab would otherwise set the preview's size, not the pads."""
    dest = tmp / pretty.name
    dest.mkdir()
    for f in pretty.glob("*.kicad_mod"):
        fp = parse(f.read_text(encoding="utf-8"))
        fp[:] = [c for c in fp if not (isinstance(c, list) and c and c[0] == "fp_text")]
        for p in find_all(fp, "property"):
            if p[1] in ("Reference", "Value"):
                hide = find(p, "hide")
                if hide is None:
                    p.append([Sym("hide"), Sym("yes")])
                else:
                    hide[1:] = [Sym("yes")]
        write_text(dest / f.name, dumps(fp))
    return dest


def _digest(src: Path) -> str:
    h = hashlib.sha256(f"{RENDER_VERSION} {FP_LAYERS};".encode("utf-8"))
    files = sorted(src.glob("*.kicad_mod")) if src.is_dir() else [src]
    for f in files:
        h.update(f.name.encode("utf-8") + b"\0" + f.read_bytes() + b"\0")
    return h.hexdigest()


def render_previews(root: Path, svg_dir: Path, run=subprocess.run) -> list[str]:
    """Render symbols/<Lib>.kicad_sym into svg_dir/sym/<Lib>/ and
    footprints/<Lib>.pretty into svg_dir/fp/<Lib>/ with kicad-cli, skipping
    libraries unchanged since their last successful render. Returns notes."""
    from .kicad import find_kicad_cli
    root = Path(root)
    cli = str(find_kicad_cli() or "kicad-cli")
    jobs = [("sym", f, f.stem) for f in sorted((root / "symbols").glob("*.kicad_sym"))]
    jobs += [("fp", d, d.stem) for d in sorted((root / "footprints").glob("*.pretty"))]
    notes: list[str] = []
    for kind in ("sym", "fp"):
        wanted = {lib for k, _, lib in jobs if k == kind}
        base = svg_dir / kind
        if base.exists():
            for d in base.iterdir():
                if d.is_dir() and d.name not in wanted:
                    shutil.rmtree(d)
    for kind, src, lib in jobs:
        out = svg_dir / kind / lib
        digest = _digest(src)
        stamp = out / HASH_FILE
        if stamp.exists() and stamp.read_text(encoding="utf-8") == digest:
            continue
        if out.exists():
            shutil.rmtree(out)
        out.mkdir(parents=True)
        with tempfile.TemporaryDirectory() as tmp:
            cmd = [cli, kind, "export", "svg", str(src), "-o", str(out)]
            if kind == "fp":
                cmd[4] = str(_textless_copy(src, Path(tmp)))
                cmd += ["-l", FP_LAYERS, "--sp"]
            r = run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode != 0:
            shutil.rmtree(out)
            lines = [ln for ln in (r.stderr or r.stdout or "").splitlines() if ln.strip()]
            notes.append(f"preview of {lib} failed: {lines[-1].strip() if lines else f'exit {r.returncode}'}")
            continue
        stamp.write_text(digest, encoding="utf-8")
    return notes


def _unit(path: Path) -> int:
    tail = path.stem.rpartition("_unit")[2]
    return int(tail) if tail.isdigit() else 0


def _svg_map(svg_dir: Path) -> dict:
    out: dict = {}
    rel = svg_dir.name
    for d in sorted((svg_dir / "sym").glob("*")) if (svg_dir / "sym").exists() else []:
        by_part: dict[str, list[Path]] = {}
        for f in d.glob("*_unit*.svg"):
            by_part.setdefault(f.stem.rpartition("_unit")[0], []).append(f)
        for name, files in by_part.items():
            out[("sym", d.name, name)] = [f"{rel}/sym/{d.name}/{f.name}" for f in sorted(files, key=_unit)]
    for d in sorted((svg_dir / "fp").glob("*")) if (svg_dir / "fp").exists() else []:
        for f in d.glob("*.svg"):
            out[("fp", f"{d.name}:{f.stem}")] = f"{rel}/fp/{d.name}/{f.name}"
    return out


def write_review(root: Path, *, previews: bool | None = None, run=subprocess.run) -> Path:
    """Write build/review/{index.html,data.js} (and previews); returns the index path."""
    root = Path(root)
    out = root / REVIEW_DIR
    out.mkdir(parents=True, exist_ok=True)
    render, note = previews_wanted(previews)
    notes = [note] if note else []
    svgs: dict = {}
    if render:
        notes += render_previews(root, out / "svg", run=run)
        svgs = _svg_map(out / "svg")
    write_text(out / "data.js", js_assign("LIB_DATA", review_data(root, svgs, notes, previews=render)))
    shutil.copyfile(PAGE, out / "index.html")
    return out / "index.html"

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
from datetime import datetime
from pathlib import Path

from .parts import Issue, Part, load_parts, validate
from .pins import pin_pad_issues
from .schema import Schema, load_schema
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
    labels = {f.key: f.label or f.key for f in schema.fields_for(cat)}
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


def write_review(root: Path, *, previews: bool | None = None, run=subprocess.run) -> Path:
    """Write build/review/{index.html,data.js}; returns the index path."""
    root = Path(root)
    out = root / REVIEW_DIR
    out.mkdir(parents=True, exist_ok=True)
    render, note = previews_wanted(previews)
    notes = [note] if note else []
    svgs: dict = {}
    write_text(out / "data.js", js_assign("LIB_DATA", review_data(root, svgs, notes, previews=render)))
    shutil.copyfile(PAGE, out / "index.html")
    return out / "index.html"

"""Bulk add of discrete MPN series (plan 8): `BZT52C{}` × zener values.

One row per value code: the MPN is the pattern with the code filled in. JLC's
keyword search gives the candidates, pick_discrete() chooses one by the
selection rules, and add.prepare() builds the entry exactly as a single add
would (stock footprint of the package, base symbol, pin/pad check). A part
that would need its own symbol is a "none" row: that is a single add.

The dry run's rows are kept in .libkit/bulk-plan-discrete-<pattern>-<package>.json;
--write loads every row's staged single-add plan and writes them together
(add.apply_many), so what lands is what was approved.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from .bulk import PLAN_DIR, PLAN_MAX_AGE, Row
from .discretes import FOOTPRINTS, classify
from .parts import load_parts
from .schema import load_schema

SUFFIX_START = "-/,_ "  # what may follow the series MPN: a packaging/grade suffix


def series_member(mpn: str, candidate: str) -> bool:
    """True when `candidate` is `mpn` itself or `mpn` plus a packaging suffix
    (BZT52C3V3-7-F, SMAJ5.0A/TR13) — not a neighbour series (BZT52C3V3S)."""
    a, b = mpn.strip().casefold(), candidate.strip().casefold()
    return b == a or (b.startswith(a) and b[len(a)] in SUFFIX_START)


def _mpn(pattern: str, value: str) -> str:
    return pattern.replace("{}", value)


def _check_run(pattern: str, package: str) -> None:
    if pattern.count("{}") != 1:
        raise ValueError(f"--mpn needs exactly one {{}} for the value, e.g. BZT52C{{}}, not {pattern!r}")
    if package not in FOOTPRINTS:
        raise ValueError(f"--package {package!r}: one of {', '.join(FOOTPRINTS)}")


def plan_options(package: str) -> dict:
    """The add.prepare options every row of a run in `package` uses."""
    ref, family = FOOTPRINTS[package]
    return dict(category=None, symbol=None, footprint=f"stock:{ref}", family=family, fp_name=None, name=None,
                pin_types=None)


def _no_easyeda(lcsc, workdir):
    raise ValueError("no base symbol fits: needs a single add (libkit add)")


def plan(root: Path, pattern: str, values: list[str], package: str, search=None, lang=None,
         kicad_share_dir: Path | None = None, fetch=None) -> list[Row]:
    """Rows for `pattern` × `values` in `package`. Never writes the library
    (each new row's single-add plan is staged in .libkit/add/<LCSC>/)."""
    from .add import prepare
    from .jlc import search as jlc_search
    from .pick import pick_discrete
    root = Path(root)
    _check_run(pattern, package)
    search = search or (lambda kw: jlc_search(kw, pages=2))
    schema = load_schema(root)
    library = [p for p in load_parts(root, schema) if p.data.get("status") == "active"]
    by_lcsc = {p.data["lcsc"]: p for p in library if p.data.get("lcsc")}
    rows: list[Row] = []
    for value in values:
        mpn = _mpn(pattern, value)
        have = next((p for p in library if series_member(mpn, p.data.get("mpn", ""))), None)
        if have is not None:
            rows.append(Row(value, have.name, "exists", have.data, "already in library"))
            continue
        cands = [p for p in search(mpn) if series_member(mpn, p.mpn)]
        result = pick_discrete(mpn, package, cands, schema, lang=lang)
        if result.part is None:
            rows.append(Row(value, "", "none", None, result.note))
            continue
        part = result.part
        if part.lcsc in by_lcsc:
            old = by_lcsc[part.lcsc]
            rows.append(Row(value, old.name, "exists", old.data, f"{part.lcsc} already in library as {old.name}"))
            continue
        disc = classify(part)
        if disc is None or disc.symbol is None:
            why = disc.why if disc is not None else f"not a diode, LED or transistor ({part.type_name})"
            rows.append(Row(value, "", "none", None, f"{part.lcsc}: no base symbol ({why}): needs a single add"))
            continue
        ds = result.datasheet
        try:
            staged = prepare(root, part.lcsc, **{k: v for k, v in plan_options(package).items() if v},
                             resolve=lambda _ref, part=part: part, fetch=fetch or _no_easyeda,
                             lang=(lambda _p, ds=ds: ds) if ds is not None else None, klc=False,
                             kicad_share_dir=kicad_share_dir)
        except ValueError as e:
            rows.append(Row(value, "", "none", None, f"{part.lcsc}: {e}"))
            continue
        if staged.symbol is not None:
            rows.append(Row(value, "", "none", None, f"{part.lcsc}: no base symbol fits: needs a single add"))
            continue
        rows.append(Row(value, staged.entry["name"], "new", staged.entry,
                        "; ".join(x for x in (result.note, *staged.warnings) if x)))
    return rows


def skip_rows(rows: list[Row], values: list[str]) -> list[Row]:
    """The rows with the "new" ones at `values` marked "skipped"; a value that
    is not a new row is an error (a typo would add the part left out)."""
    new = {r.value.casefold() for r in rows if r.status == "new"}
    want = {v.strip().casefold(): v for v in values if v.strip()}
    missing = [v for k, v in want.items() if k not in new]
    if missing:
        raise ValueError(f"--skip {', '.join(missing)}: not a new row of the dry run")
    return [Row(r.value, r.name, "skipped", r.entry, "skipped (--skip)")
            if r.status == "new" and r.value.casefold() in want else r for r in rows]


def plan_file(pattern: str, package: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9.+-]", "_", pattern.replace("{}", "x"))
    return PLAN_DIR / f"bulk-plan-discrete-{safe}-{package}.json"


def _fingerprint(root: Path, run: dict) -> str:
    mpns = [_mpn(run["pattern"], v) for v in run["values"]]
    mine = sorted((p.data for p in load_parts(root, load_schema(root))
                   if any(series_member(m, p.data.get("mpn", "")) for m in mpns)),
                  key=lambda d: json.dumps(d, sort_keys=True))
    return hashlib.sha256(json.dumps(mine, sort_keys=True).encode("utf-8")).hexdigest()


def save_plan(root: Path, run: dict, rows: list[Row], now: datetime | None = None) -> Path:
    path = Path(root) / plan_file(run["pattern"], run["package"])
    data = {"created": (now or datetime.now(timezone.utc)).isoformat(timespec="seconds"),
            "run": json.loads(json.dumps(run)), "library": _fingerprint(root, run),
            "rows": [asdict(r) for r in rows]}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8", newline="\n")
    tmp.replace(path)
    return path


def load_plan(root: Path, run: dict, now: datetime | None = None) -> tuple[list[Row], datetime]:
    rerun = "run the same command without --write first"
    rel = plan_file(run["pattern"], run["package"])
    try:
        data = json.loads((Path(root) / rel).read_text(encoding="utf-8"))
        created = datetime.fromisoformat(data["created"])
        stored, rows = data["run"], [Row(**r) for r in data["rows"]]
    except FileNotFoundError:
        raise ValueError(f"no dry run to apply: {rerun}") from None
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise ValueError(f"{rel.as_posix()} is unreadable ({e}): {rerun}") from None
    if stored != json.loads(json.dumps(run)):
        raise ValueError(f"the last dry run used other options: {rerun}")
    if (now or datetime.now(timezone.utc)) - created > PLAN_MAX_AGE:
        raise ValueError(f"the last dry run is older than {PLAN_MAX_AGE.total_seconds() / 3600:g} h: {rerun}")
    if data.get("library") != _fingerprint(root, run):
        raise ValueError(f"the library's {run['pattern']} parts changed since the last dry run: {rerun}")
    return rows, created


def apply(root: Path, run: dict, rows: list[Row]) -> int:
    """Write every "new" row (its staged single-add plan) in one go, then build."""
    from .add import apply_many, clear_plan
    from .add import load_plan as load_add
    new = [r for r in rows if r.status == "new"]
    if not new:
        return 0
    opts = plan_options(run["package"])
    plans = [load_add(root, r.entry["lcsc"], opts) for r in new]
    apply_many(root, plans)
    for r in new:
        clear_plan(root, r.entry["lcsc"])
    return len(new)


def clear(root: Path, run: dict) -> None:
    (Path(root) / plan_file(run["pattern"], run["package"])).unlink(missing_ok=True)

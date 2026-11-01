"""Bulk add of resistors and capacitors by value series (spec §6.7).

plan() decides per value: an existing part already covers it ("exists"), a
new pick by the selection rules ("new"), or no usable part ("none"). It never
writes. apply() writes all new rows in one category rewrite, then builds.

The dry run's rows are kept in .libkit/bulk-plan-<kind>-<package>.json
(save_plan), so runs for several kinds and packages can be approved together;
--write applies exactly those (load_plan) instead of picking again, so what
lands in the library is what was approved. load_plan refuses a plan made with
other options, older than PLAN_MAX_AGE, or made before the library's parts of
that kind and package changed. Parts of other kinds or packages cannot change
a plan: names carry kind and package, and a C-number is one package
(apply() validates the whole library anyway).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import jlcsearch, series
from .entries import KINDS, POLAR, passive_entry
from .parts import Part, load_parts, validate, write_category
from .pick import Need, pick, pick_polar, pick_ranked
from .polar import candidates as polar_candidates
from .polar import package_name
from .schema import load_schema
from .values import format_value, parse_value

PLAN_DIR = Path(".libkit")
PLAN_MAX_AGE = timedelta(hours=24)


@dataclass
class Row:
    value: str
    name: str
    status: str  # "new" | "exists" | "none"
    entry: dict | None
    note: str


def _num(text: str, pattern: str) -> float | None:
    m = re.fullmatch(pattern, text.strip())
    return float(m.group(1)) if m else None


def _mismatch(d: dict, value: float, unit: str, need: Need) -> str | None:
    """Why part data `d` does not satisfy the need, or None when it does."""
    if d.get("package") != need.package:
        return f"package {d.get('package')}"
    try:
        v = parse_value(d.get("value", ""), unit)
    except ValueError:
        return f"value {d.get('value')!r}"
    if abs(v - value) > jlcsearch.VALUE_MATCH * value:
        return f"value {d.get('value')}"
    tol = _num(d.get("tolerance", ""), r"±?\s*(\d+(?:\.\d+)?)\s*%")
    if tol is None or tol / 100 > need.max_tolerance + 1e-12:
        return f"tolerance {d.get('tolerance')}"
    if need.min_power is not None:
        watts = power_watts(d.get("power", ""))
        if watts is None or watts < need.min_power - 1e-12:
            return f"power {d.get('power')}"
    if need.kind == "capacitor":
        volts = _num(d.get("voltage", ""), r"(\d+(?:\.\d+)?)\s*V")
        if need.min_voltage is not None and (volts is None or volts < need.min_voltage):
            return f"voltage {d.get('voltage')}"
        if d.get("dielectric", "").upper() not in {x.upper() for x in need.dielectrics}:
            return f"dielectric {d.get('dielectric')}"
    return None


def power_watts(text: str) -> float | None:
    """1W, 500mW, 1/4W, 62.5mW -> watts; None when not understood."""
    m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)(?:/(\d+))?\s*(m?)W\s*", text or "")
    if not m:
        return None
    v = float(m.group(1)) / (float(m.group(2)) if m.group(2) else 1)
    return v / 1000 if m.group(3) else v


def _fits(p: Part, value: float, unit: str, need: Need) -> bool:
    """An active library part that already satisfies the need."""
    return p.data.get("status") == "active" and _mismatch(p.data, value, unit, need) is None


def plan(root: Path, kind: str, series_name: str, start: float, stop: float, package: str,
         max_tolerance: float, min_voltage: float | None, dielectrics: tuple[str, ...],
         min_power: float | None = None, family: bool = False, get=None, lookup=None, lang=None,
         search=None) -> list[Row]:
    """`lang` (part -> datasheet.Result) turns on the English-datasheet preference
    and fills in `datasheet_lang`; the CLI passes datasheet.Checker(root).for_part."""
    root = Path(root)
    if kind not in KINDS:
        raise ValueError(f"bulk-add supports {', '.join(KINDS)}, not {kind!r}")
    category, _, unit, _ = KINDS[kind]
    schema = load_schema(root)
    library = load_parts(root, schema)
    existing = [p for p in library if p.category == category]
    names = {p.name: p for p in library}
    by_lcsc = {p.data["lcsc"]: p for p in names.values() if p.data.get("lcsc")}
    if kind in ("bead", "inductor"):
        return _plan_ranked(root, kind, series_name, start, stop, package, family, schema, existing, names,
                            by_lcsc, search, lang)
    if kind in POLAR:
        return _plan_polar(kind, series_name, start, stop, package, min_voltage, schema, existing, names, by_lcsc,
                           search, lang, max_tolerance)
    search = jlcsearch.resistors if kind == "resistor" else jlcsearch.capacitors

    rows: list[Row] = []
    for v in series.values(series_name, start, stop):
        text = format_value(v, unit)
        need = Need(kind, v, package, max_tolerance, min_voltage if kind == "capacitor" else None,
                    **({"dielectrics": tuple(dielectrics)} if kind == "capacitor" else {}),
                    min_power=min_power if kind == "resistor" else None)
        have = next((p for p in existing if _fits(p, v, unit, need)), None)
        if have is not None:
            rows.append(Row(text, have.name, "exists", have.data, "already in library"))
            continue
        built: dict[str, dict] = {}

        def check(part, need=need, v=v, built=built):
            # The entry is built from JLC's own record; it must still meet the
            # request (jlcsearch's figures can be stale or incomplete).
            try:
                e = passive_entry(kind, part, schema)
            except ValueError as ex:
                return str(ex)
            why = _mismatch(e, v, unit, need)
            if why:
                return f"{part.lcsc}: {why} at JLC"
            built[part.lcsc] = e
            return None

        result = pick(need, search(package, v, get=get), schema, lookup=lookup, check=check, lang=lang)
        if result.part is None:
            rows.append(Row(text, "", "none", None, result.note))
            continue
        entry = built[result.part.lcsc]
        if result.datasheet is not None:
            entry["datasheet_lang"] = result.datasheet.lang
        if entry["name"] in names:
            old = names[entry["name"]]
            rows.append(Row(text, entry["name"], "exists", old.data,
                            f"name already in library ({old.data.get('status', '?')}, {old.data.get('lcsc', '-')})"))
        elif entry["lcsc"] in by_lcsc:
            old = by_lcsc[entry["lcsc"]]
            rows.append(Row(text, entry["name"], "exists", old.data,
                            f"{entry['lcsc']} already in library as {old.name}"))
        else:
            rows.append(Row(text, entry["name"], "new", entry, result.note))
    return rows


def _new_or_existing(text: str, entry: dict, note: str, names: dict, by_lcsc: dict) -> Row:
    if entry["name"] in names:
        old = names[entry["name"]]
        return Row(text, entry["name"], "exists", old.data,
                   f"name already in library ({old.data.get('status', '?')}, {old.data.get('lcsc', '-')})")
    if entry["lcsc"] in by_lcsc:
        old = by_lcsc[entry["lcsc"]]
        return Row(text, entry["name"], "exists", old.data, f"{entry['lcsc']} already in library as {old.name}")
    return Row(text, entry["name"], "new", entry, note)


def _plan_ranked(root, kind, series_name, start, stop, package, family, schema, existing, names, by_lcsc,
                 search, lang) -> list[Row]:
    """Chip beads/inductors (package = chip size) or a power-inductor family
    (package = family prefix, family=True): one part per value (plan 7)."""
    from . import beads, families
    unit = KINDS[kind][2]
    footprint = None
    if family:
        if kind != "inductor":
            raise ValueError("--family applies to inductors only")
        footprint = families.family_footprint(root, package)
        if footprint is None:
            raise ValueError(f"no footprint for family {package} yet: import one member first, e.g. "
                             f"libkit add <C-number> --category inductors --family Inductor_SMD "
                             f"--fp-name L_<Brand>_{package}, then run this again")
    rows: list[Row] = []
    for v in series.values(series_name, start, stop):
        text = format_value(v, unit) + ("@100MHz" if kind == "bead" else "")
        have = next((p for p in existing if p.data.get("status") == "active" and p.data.get("symbol") == KINDS[kind][1]
                     and (families.family_member(package, p.data.get("mpn", "")) if family
                          else p.data.get("package") == package)
                     and abs(parse_value(p.data.get("value", "0").split("@")[0], unit) - v) <= 0.01 * v), None)
        if have is not None:
            rows.append(Row(text, have.name, "exists", have.data, "already in library"))
            continue
        cands = (families.candidates(package, v, search=search) if family
                 else beads.candidates(kind, v, package, search=search))
        result = pick_ranked(kind, v, package, cands, schema, lang=lang, footprint=footprint)
        if result.part is None:
            rows.append(Row(text, "", "none", None, result.note))
            continue
        entry = passive_entry(kind, result.part, schema, footprint=footprint)
        if result.datasheet is not None:
            entry["datasheet_lang"] = result.datasheet.lang
        rows.append(_new_or_existing(text, entry, result.note, names, by_lcsc))
    return rows


def _plan_polar(kind, series_name, start, stop, size, min_voltage, schema, existing, names, by_lcsc,
                search, lang, max_tolerance=1.0) -> list[Row]:
    """Tantalum/electrolytic rows: one part per value and case/can (plan 6)."""
    package = package_name(kind, size)
    rows: list[Row] = []
    for v in series.values(series_name, start, stop):
        text = format_value(v, "F")
        have = next((p for p in existing if p.data.get("status") == "active"
                     and p.data.get("package") == package and p.data.get("dielectric") == POLAR[kind]
                     and abs(parse_value(p.data.get("value", "0F"), "F") - v) <= 0.01 * v
                     and (min_voltage is None or float(p.data.get("voltage", "0V").rstrip("V")) >= min_voltage)
                     and (_num(p.data.get("tolerance", ""), r"±?\s*(\d+(?:\.\d+)?)\s*%") or 100) / 100
                     <= max_tolerance + 1e-12),
                    None)
        if have is not None:
            rows.append(Row(text, have.name, "exists", have.data, "already in library"))
            continue
        result = pick_polar(kind, v, size, polar_candidates(kind, v, size, search=search), schema,
                            lang=lang, min_voltage=min_voltage, max_tolerance=max_tolerance)
        if result.part is None:
            rows.append(Row(text, "", "none", None, result.note))
            continue
        entry = passive_entry(kind, result.part, schema)
        if result.datasheet is not None:
            entry["datasheet_lang"] = result.datasheet.lang
        rows.append(_new_or_existing(text, entry, result.note, names, by_lcsc))
    return rows


def apply(root: Path, kind: str, rows: list[Row]) -> int:
    """Write every "new" row into parts/<category>.yaml in one rewrite, then build."""
    from .build import build
    root = Path(root)
    new = [r.entry for r in rows if r.status == "new"]
    if not new:
        return 0
    category = KINDS[kind][0]
    schema = load_schema(root)
    library = load_parts(root, schema)
    added = [Part(e["name"], category, e, root / "parts" / f"{category}.yaml") for e in new]
    bad = [i for i in validate(library + added, schema) if i.severity == "error"]
    if bad:
        raise ValueError("refusing to write invalid parts: " + "; ".join(str(i) for i in bad))
    write_category(root, category, [p.data for p in library if p.category == category] + new)
    build(root)
    return len(new)


def skip_rows(rows: list[Row], values: list[str], unit: str) -> list[Row]:
    """The rows with the "new" ones at `values` (e.g. "62k") marked "skipped".
    A value that is not a "new" row of the plan is an error (a typo would
    otherwise add the part the user wanted left out)."""
    want = {format_value(parse_value(v, unit), unit): v for v in values}
    new = {r.value for r in rows if r.status == "new"}
    missing = [v for k, v in want.items() if k not in new]
    if missing:
        raise ValueError(f"--skip {', '.join(missing)}: not a new row of the dry run")
    return [Row(r.value, r.name, "skipped", r.entry, "skipped (--skip)") if r.status == "new" and r.value in want
            else r for r in rows]


def plan_file(kind: str, package: str) -> Path:
    """Where the dry run for `kind` in `package` is kept, relative to the library root."""
    return PLAN_DIR / f"bulk-plan-{kind}-{package}.json"


def _fingerprint(root: Path, kind: str, package: str) -> str:
    """Hash of the library's parts of this kind and package: what a plan was made against."""
    category = KINDS[kind][0]
    if kind in POLAR:
        package = package_name(kind, package)
    from .families import family_member
    mine = sorted((p.data for p in load_parts(root, load_schema(root))
                   if p.category == category and (p.data.get("package") == package
                                                  or family_member(package, p.data.get("mpn", "")))),
                  key=lambda d: json.dumps(d, sort_keys=True))
    return hashlib.sha256(json.dumps(mine, sort_keys=True).encode("utf-8")).hexdigest()


def _normal(run: dict) -> dict:
    return json.loads(json.dumps(run))  # tuples -> lists, as stored


def save_plan(root: Path, run: dict, rows: list[Row], now: datetime | None = None) -> Path:
    """Keep a dry run's rows for --write. `run` holds the plan() options."""
    path = Path(root) / plan_file(run["kind"], run["package"])
    data = {
        "created": (now or datetime.now(timezone.utc)).isoformat(timespec="seconds"),
        "run": _normal(run),
        "library": _fingerprint(root, run["kind"], run["package"]),
        "rows": [asdict(r) for r in rows],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
    return path


def load_plan(root: Path, run: dict, now: datetime | None = None) -> tuple[list[Row], datetime]:
    """The rows of the last dry run with exactly these options, and when it ran."""
    rerun = "run the same command without --write first"
    rel = plan_file(run["kind"], run["package"])
    path = Path(root) / rel
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        created = datetime.fromisoformat(data["created"])
        stored, rows = data["run"], [Row(**r) for r in data["rows"]]
    except FileNotFoundError:
        raise ValueError(f"no dry run to apply: {rerun}") from None
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise ValueError(f"{rel.as_posix()} is unreadable ({e}): {rerun}") from None
    want = _normal(run)
    if stored != want:
        diff = ", ".join(f"{k} {stored.get(k)!r} vs {want.get(k)!r}"
                         for k in sorted(set(stored) | set(want)) if stored.get(k) != want.get(k))
        raise ValueError(f"the last dry run used other options ({diff}): {rerun}")
    if (now or datetime.now(timezone.utc)) - created > PLAN_MAX_AGE:
        raise ValueError(f"the last dry run is older than {PLAN_MAX_AGE.total_seconds() / 3600:g} h: {rerun}")
    if data.get("library") != _fingerprint(root, run["kind"], run["package"]):
        raise ValueError(f"the library's {run['package']} {KINDS[run['kind']][0]} changed since the last dry run: "
                         f"{rerun}")
    return rows, created


def clear_plan(root: Path, kind: str, package: str) -> None:
    (Path(root) / plan_file(kind, package)).unlink(missing_ok=True)

"""Command line: python -m libkit <command>."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .kicad import kicad_share
from .net import NetError
from .schema import SCHEMA_FILE, load_schema


def find_root(start: Path | None = None) -> Path:
    here = (start or Path.cwd()).resolve()
    for d in (here, *here.parents):
        if (d / SCHEMA_FILE).exists():
            return d
    raise SystemExit(f"no {SCHEMA_FILE.as_posix()} found in {here} or any parent folder")


def _vendor_fp(args) -> int:
    from .vendor import vendor_footprint
    root = find_root()
    fams = load_schema(root).families
    if args.family not in fams:
        print(f"unknown family {args.family!r}; known: {', '.join(fams)}", file=sys.stderr)
        return 1
    out = vendor_footprint(args.ref, fams[args.family], root, kicad_share())
    print(f"wrote {out.relative_to(root).as_posix()}")
    return 0


def _vendor_sym(args) -> int:
    from .vendor import vendor_symbol
    root = find_root()
    dest = root / "src" / "symbols" / f"{args.into}.kicad_sym"
    vendor_symbol(args.ref, dest, kicad_share())
    print(f"updated {dest.relative_to(root).as_posix()}")
    return 0


def _print_issues(issues) -> None:
    for i in issues:
        print(i, file=sys.stderr if i.severity == "error" else sys.stdout)


def _build(args) -> int:
    from .build import BuildError, build
    from .parts import load_parts, validate
    root = find_root()
    try:
        written = build(root)
    except BuildError as e:
        _print_issues(e.issues)
        return 1
    schema = load_schema(root)
    _print_issues([i for i in validate(load_parts(root, schema), schema, root) if i.severity == "warning"])
    print(f"built {len(written)} files")
    print("review page: build/review/index.html")
    return 0


def _check(args) -> int:
    from .check import check
    from .parts import Issue
    from .review import write_check_results
    root = find_root()
    try:
        issues = check(root, klc=not args.no_klc)
    except ValueError as e:  # parts or schema do not load
        issues = [Issue("error", None, str(e))]
    _print_issues(issues)
    write_check_results(root, issues, klc=not args.no_klc)
    n_err = sum(i.severity == "error" for i in issues)
    print(f"check: {n_err} errors, {len(issues) - n_err} warnings")
    return 1 if n_err else 0


def _fetch_klc(args) -> int:
    from .klc import fetch_klc
    print(f"KLC checker ready in {fetch_klc(find_root())}")
    return 0


def _jlc(args) -> int:
    from dataclasses import asdict
    from .datasheet import Checker
    from .jlc import lookup
    root = find_root()
    schema = load_schema(root)
    part = lookup(args.lcsc)
    if part is None:
        print(f"{args.lcsc}: not found at JLC", file=sys.stderr)
        return 1
    for k, v in asdict(part).items():
        if k == "attributes":
            print("attributes:")
            for an, av in v.items():
                print(f"  {an}: {av}")
        else:
            print(f"{k}: {v}")
    print(f"canonical manufacturer: {schema.canonical_manufacturer(part.brand) or 'unknown'}")
    ds = Checker(root).for_part(part)
    print(f"datasheet language: {ds.lang}" + (f" ({ds.note})" if ds.note else ""))
    return 0


def _percent(text: str, what: str) -> float:
    t = text.strip().rstrip("%").lstrip("±")
    try:
        return float(t) / 100
    except ValueError:
        raise ValueError(f"{what} {text!r} is not a percentage like 1%") from None


def _volts(text: str) -> float:
    try:
        return float(text.strip().rstrip("Vv"))
    except ValueError:
        raise ValueError(f"voltage {text!r} is not like 16V") from None


def _bulk_add(args) -> int:
    from .bulk import apply, clear_plan, load_plan, plan, save_plan, skip_rows
    from .datasheet import Checker
    from .entries import KINDS
    from .values import parse_value
    root = find_root()
    unit = KINDS[args.kind][2]
    if args.kind == "capacitor" and args.voltage is None:
        raise ValueError("capacitors need --voltage")
    run = dict(
        kind=args.kind, series_name=args.series,
        start=parse_value(args.start, unit), stop=parse_value(args.stop, unit),
        package=args.package, max_tolerance=_percent(args.tolerance, "tolerance"),
        min_voltage=_volts(args.voltage) if args.voltage else None,
        dielectrics=tuple(d.strip() for d in args.dielectric.split(",") if d.strip()),
    )
    if args.skip and not args.write:
        raise ValueError("--skip only applies with --write (the dry run keeps every row)")
    if args.write:
        rows, created = load_plan(root, run)  # exactly the approved dry run, no new picks
        if args.skip:
            rows = skip_rows(rows, [v.strip() for v in args.skip.split(",") if v.strip()], unit)
    else:
        rows = plan(root, **run, lang=Checker(root).for_part)
    table = [("value", "name", "status", "LCSC", "MPN", "manufacturer", "type", "ds", "stock", "note")]
    for r in rows:
        e = r.entry or {}
        table.append((r.value, r.name or "-", r.status, e.get("lcsc", "-"), e.get("mpn", "-"),
                      e.get("manufacturer", "-"), e.get("jlc_type", "-"), e.get("datasheet_lang", "-"),
                      e.get("stock", "-"), r.note))
    widths = [max(len(str(row[i])) for row in table) for i in range(len(table[0]) - 1)]
    for row in table:
        print("  ".join(str(c).ljust(w) for c, w in zip(row, widths)) + "  " + row[-1])
    count = {s: sum(r.status == s for r in rows) for s in ("new", "exists", "none", "skipped")}
    if not args.write:
        save_plan(root, run, rows)
        print(f"dry run: {count['new']} new, {count['exists']} existing, {count['none']} without a part"
              " — rerun with --write to add exactly these")
        return 0
    n = apply(root, args.kind, rows)
    clear_plan(root, args.kind, args.package)
    print(f"added {n} parts to parts/{KINDS[args.kind][0]}.yaml from the dry run of "
          f"{created.astimezone():%Y-%m-%d %H:%M} ({count['exists']} existing, {count['none']} without a part"
          + (f", {count['skipped']} skipped" if count["skipped"] else "") + ")")
    return 0


def _table(rows: list[tuple]) -> None:
    """Print rows as aligned columns; the last column is not padded."""
    widths = [max(len(str(row[i])) for row in rows) for i in range(len(rows[0]) - 1)]
    for row in rows:
        print("  ".join(str(c).ljust(w) for c, w in zip(row, widths)) + "  " + str(row[-1]))


def _find(args) -> int:
    from .entries import KINDS
    from .find import find
    from .values import parse_value
    root = find_root()
    if args.kind == "capacitor" and args.voltage is None:
        raise ValueError("capacitors need --voltage")
    opts = find(root, args.kind, parse_value(args.value, KINDS[args.kind][2]), args.package,
                max_tolerance=_percent(args.tolerance, "tolerance") if args.tolerance else None,
                min_voltage=_volts(args.voltage) if args.voltage else None,
                dielectrics=tuple(d.strip() for d in args.dielectric.split(",") if d.strip()),
                limit=args.limit)
    if not opts:
        print("no candidates")
        return 0
    rows = [("LCSC", "MPN", "manufacturer", "type", "stock", "tol", "V/current", "dielectric/DCR", "name", "notes")]
    for o in opts:
        e = o.entry or {}
        rows.append((o.part.lcsc, o.part.mpn, e.get("manufacturer", o.part.brand), o.part.jlc_type, o.part.stock,
                     e.get("tolerance", "-"), e.get("voltage") or e.get("current_rating") or "-",
                     e.get("dielectric") or e.get("dcr") or "-", e.get("name", "-"), "; ".join(o.notes)))
    _table(rows)
    return 0


def _pin_types(text: str | None) -> dict[str, str] | None:
    if not text:
        return None
    out = {}
    for item in text.split(","):
        key, sep, kind = item.partition("=")
        if not sep or not key.strip() or not kind.strip():
            raise ValueError(f"--pin-types item {item!r} is not like EN=input or #4=passive")
        out[key.strip()] = kind.strip()
    return out


def _add(args) -> int:
    import yaml
    from .add import CHECKLIST, apply, clear_plan, load_plan, local_options, prepare, prepare_local
    from .datasheet import Checker
    root = find_root()
    if args.local:
        given = [o for o in ("fp_name", "name", "pin_types") if getattr(args, o)]
        if given:
            raise ValueError(f"--{given[0].replace('_', '-')} does not apply to --local parts")
        if not args.category or not args.footprint:
            raise ValueError("--local needs --category and --footprint")
        options = dict(category=args.category, symbol=args.symbol, footprint=args.footprint, family=args.family,
                       value=args.value, description=args.description)
    else:
        if args.value or args.description:
            raise ValueError("--value and --description only apply with --local")
        options = dict(category=args.category, symbol=args.symbol, footprint=args.footprint, family=args.family,
                       fp_name=args.fp_name, name=args.name, pin_types=_pin_types(args.pin_types))
    if args.write:
        plan = load_plan(root, args.ref, local_options(**options) if args.local else options)
        written = apply(root, plan)
        clear_plan(root, args.ref)
        print(f"added {plan.entry['name']} to parts/{plan.category}.yaml")
        for f in written:
            print(f"  wrote {f.relative_to(root).as_posix()}")
        return 0
    if args.local:
        plan = prepare_local(root, args.ref, **options, klc=not args.no_klc, previews=True)
    else:
        plan = prepare(root, args.ref, **options, lang=Checker(root).for_part, klc=not args.no_klc, previews=True)
    print(yaml.safe_dump(plan.entry, allow_unicode=True, sort_keys=False, width=1000).rstrip())
    if plan.new_family:
        print(f"new footprint family: {plan.new_family} (declared in schema/library.yaml on --write)")
    if plan.symbol:
        print(f"new symbol: {plan.entry['name']} in src/symbols/{plan.category}.kicad_sym")
    for rel in plan.files:
        print(f"new file: {rel}")
    for head, items in (("warning", plan.warnings), ("note", plan.notes), ("KLC", plan.klc),
                        ("preview", plan.previews)):
        for i in items:
            print(f"{head}: {i}")
    print(CHECKLIST)
    print("dry run — rerun with --write to add exactly this")
    return 0


def _refresh_stock(args) -> int:
    from .parts import load_parts
    from .stock import refresh
    root = find_root()
    changes = refresh(root)
    for c in changes:
        print(c)
    listed = sum(1 for p in load_parts(root, load_schema(root)) if p.data.get("lcsc"))
    print(f"refreshed {listed - sum(c.kind == 'not_found' for c in changes)} parts")
    if any(c.kind == "type_changed" for c in changes):
        return _build(args)
    return 0


def _utf8_output() -> None:
    # Part data has Ω, ±, ℃; Windows pipes default to cp1252, which lacks some.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    _utf8_output()
    ap = argparse.ArgumentParser(prog="libkit")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("build", help="generate symbol libraries and library tables")
    p.set_defaults(func=_build)

    p = sub.add_parser("check", help="validate data, references, generated files and KLC rules")
    p.add_argument("--no-klc", action="store_true", help="skip the KLC checks")
    p.set_defaults(func=_check)

    p = sub.add_parser("fetch-klc", help="install kicad-library-utils at the pinned commit")
    p.set_defaults(func=_fetch_klc)

    p = sub.add_parser("vendor-fp", help="copy a stock KiCad footprint (+3D model) into a family")
    p.add_argument("ref", help="<StockLib>:<Footprint>")
    p.add_argument("--family", required=True)
    p.set_defaults(func=_vendor_fp)

    p = sub.add_parser("vendor-sym", help="copy a stock KiCad symbol into src/symbols/<into>.kicad_sym")
    p.add_argument("ref", help="<StockLib>:<Symbol>")
    p.add_argument("--into", required=True)
    p.set_defaults(func=_vendor_sym)

    p = sub.add_parser("bulk-add", help="add resistors or capacitors for a value series (dry run by default)")
    p.add_argument("kind", choices=["resistor", "capacitor"])
    p.add_argument("--series", required=True, choices=["E6", "E12", "E24", "E48", "E96"])
    p.add_argument("--from", dest="start", required=True, help="first value, e.g. 1k or 10n")
    p.add_argument("--to", dest="stop", required=True, help="last value (inclusive)")
    p.add_argument("--package", required=True, choices=["0402", "0603", "0805", "1206"])
    p.add_argument("--tolerance", required=True, help="worst acceptable tolerance, e.g. 1%%")
    p.add_argument("--voltage", help="minimum voltage rating for capacitors, e.g. 16V")
    p.add_argument("--dielectric", default="C0G,NP0,X7R,X5R", help="allowed dielectrics (default %(default)s)")
    p.add_argument("--write", action="store_true",
                   help="write the new parts of the last dry run with these options, then build")
    p.add_argument("--skip", help="with --write: values of the dry run not to add, e.g. 62k,1.8k")
    p.set_defaults(func=_bulk_add)

    p = sub.add_parser("find", help="list JLC candidates for one passive value (network)")
    p.add_argument("kind", choices=["resistor", "capacitor", "inductor", "bead"])
    p.add_argument("value", help="e.g. 62k, 680n, 10u, 600R (bead impedance)")
    p.add_argument("--package", required=True, help="e.g. 0402")
    p.add_argument("--tolerance", help="worst acceptable tolerance, e.g. 1%%")
    p.add_argument("--voltage", help="minimum voltage rating for capacitors, e.g. 25V")
    p.add_argument("--dielectric", default="C0G,NP0,X7R,X5R", help="allowed dielectrics (default %(default)s)")
    p.add_argument("--limit", type=int, default=10, help="rows to show (default %(default)s)")
    p.set_defaults(func=_find)

    p = sub.add_parser("add", help="add one part by C-number or MPN (dry run by default; network)")
    p.add_argument("ref", help="LCSC C-number (C6186) or exact MPN; with --local the part name")
    p.add_argument("--category", help="category key, e.g. ics_power (not for chip passives)")
    p.add_argument("--symbol", help="easyeda (default), stock:<Lib>:<Name>, or a symbol in src/symbols")
    p.add_argument("--footprint", help="easyeda (default), stock:<Lib>:<Name>, or LIB_<Family>:<Name>")
    p.add_argument("--family", help="footprint family for a new footprint, e.g. Package_TO_SOT")
    p.add_argument("--fp-name", help="KLC name for an EasyEDA footprint, e.g. SOT-223-3_TabPin2")
    p.add_argument("--name", help="part name instead of the MPN")
    p.add_argument("--pin-types", help="EasyEDA symbols: pin types, e.g. EN=input,#4=passive")
    p.add_argument("--local", action="store_true",
                   help="a part without a C-number (non-orderable category, e.g. mechanical): ref is its name")
    p.add_argument("--value", help="--local: value field (default: the name)")
    p.add_argument("--description", help="--local: description (default: the footprint's)")
    p.add_argument("--no-klc", action="store_true", help="skip the KLC checks of the staged files")
    p.add_argument("--write", action="store_true", help="apply the last dry run with these options, then build")
    p.set_defaults(func=_add)

    p = sub.add_parser("refresh-stock", help="re-query stock and JLC type of every part")
    p.set_defaults(func=_refresh_stock)

    p = sub.add_parser("jlc", help="look up one LCSC part at JLC and print its record")
    p.add_argument("lcsc", help="LCSC C-number, e.g. C1525")
    p.set_defaults(func=_jlc)

    args = ap.parse_args(argv)
    try:
        return args.func(args)
    except NetError as e:
        print(f"ERROR: network: {e}", file=sys.stderr)
        return 1
    except (FileNotFoundError, KeyError, ValueError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

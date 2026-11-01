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
    return 0


def _check(args) -> int:
    from .check import check
    issues = check(find_root(), klc=not args.no_klc)
    _print_issues(issues)
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

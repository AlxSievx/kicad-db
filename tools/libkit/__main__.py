"""Command line: python -m libkit <command>."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .kicad import kicad_share
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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="libkit")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("build", help="generate symbol libraries and library tables")
    p.set_defaults(func=_build)

    p = sub.add_parser("vendor-fp", help="copy a stock KiCad footprint (+3D model) into a family")
    p.add_argument("ref", help="<StockLib>:<Footprint>")
    p.add_argument("--family", required=True)
    p.set_defaults(func=_vendor_fp)

    p = sub.add_parser("vendor-sym", help="copy a stock KiCad symbol into src/symbols/<into>.kicad_sym")
    p.add_argument("ref", help="<StockLib>:<Symbol>")
    p.add_argument("--into", required=True)
    p.set_defaults(func=_vendor_sym)

    args = ap.parse_args(argv)
    try:
        return args.func(args)
    except (FileNotFoundError, KeyError, ValueError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

"""Consistency checks over the whole library (spec §6.8)."""

from __future__ import annotations

import re
from pathlib import Path

from .build import BuildError, generate
from .klc import run_klc
from .parts import Issue, load_parts, validate
from .pins import pin_pad_issues
from .schema import load_schema
from .symgen import load_source_symbols

_MODEL = re.compile(r'\(model\s+"([^"]*)"')
_ABS = [re.compile(r'"[A-Za-z]:[\\/]'), re.compile(r'\((?:model|uri)\s+"/')]


def _norm(text: str) -> str:
    return text.replace("\r\n", "\n")


def _library_files(root: Path) -> list[Path]:
    files = sorted((root / "symbols").glob("*.kicad_sym"))
    files += sorted((root / "src" / "symbols").glob("*.kicad_sym"))
    files += sorted((root / "footprints").glob("*.pretty/*.kicad_mod"))
    files += [f for f in (root / "sym-lib-table", root / "fp-lib-table") if f.exists()]
    return files


def check(root: Path, klc: bool = True) -> list[Issue]:
    root = Path(root)
    schema = load_schema(root)
    parts = load_parts(root, schema)
    issues = validate(parts, schema, root)
    has_errors = any(i.severity == "error" for i in issues)

    # Source symbols and footprint references.
    try:
        sources = load_source_symbols(root)
    except ValueError as e:
        issues.append(Issue("error", None, str(e)))
        sources = {}
    fam_libs = {f.lib_name for f in schema.families.values()}
    for p in parts:
        sym = p.data.get("symbol")
        if sym and sources and sym not in sources:
            issues.append(Issue("error", p.name, f"symbol {sym!r} not found in src/symbols"))
        fp = p.data.get("footprint", "")
        lib, _, name = fp.partition(":")
        if not fp:
            continue
        if lib not in fam_libs:
            issues.append(Issue("error", p.name, f"footprint library {lib!r} is not a declared family"))
        elif not (root / "footprints" / f"{lib}.pretty" / f"{name}.kicad_mod").exists():
            issues.append(Issue("error", p.name, f"footprint {fp} does not exist"))
    if sources:
        issues += pin_pad_issues(parts, sources, root)
    for d in sorted((root / "footprints").glob("*.pretty")):
        if d.stem not in fam_libs:
            issues.append(Issue("error", None, f"footprints/{d.name} is not a declared family in schema"))

    # 3D models.
    for f in sorted((root / "footprints").glob("*.pretty/*.kicad_mod")):
        for m in _MODEL.finditer(f.read_text(encoding="utf-8")):
            path = m.group(1)
            if not path.startswith("${LIB_DIR}/"):
                issues.append(Issue("error", f.stem, f"3D model path must start with ${{LIB_DIR}}/: {path}"))
            elif not (root / path.removeprefix("${LIB_DIR}/")).exists():
                issues.append(Issue("error", f.stem, f"3D model missing: {path}"))

    # Absolute paths.
    for f in _library_files(root):
        text = f.read_text(encoding="utf-8")
        if any(rx.search(text) for rx in _ABS):
            issues.append(Issue("error", None, f"absolute path in {f.relative_to(root).as_posix()}"))

    # Generated files up to date.
    if not has_errors:
        try:
            generated = generate(root)
        except BuildError as e:
            issues += e.issues
            generated = {}
        for rel, text in generated.items():
            disk = root / rel
            if not disk.exists() or _norm(disk.read_text(encoding="utf-8")) != _norm(text):
                issues.append(Issue("error", None, f"stale: {rel} — run build"))

    if klc:
        targets = sorted((root / "symbols").glob("*.kicad_sym"))
        targets += sorted((root / "footprints").glob("*.pretty/*.kicad_mod"))
        issues += run_klc(root, targets)
    return issues

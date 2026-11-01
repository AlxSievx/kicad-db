"""Generate everything KiCad reads from the YAML master data."""

from __future__ import annotations

from pathlib import Path

from .parts import Issue, load_parts, validate
from .schema import load_schema
from .symgen import build_symbol_lib, load_source_symbols, write_text
from .tables import fp_lib_table, sym_lib_table


class BuildError(Exception):
    def __init__(self, issues: list[Issue]):
        self.issues = issues
        super().__init__("\n".join(str(i) for i in issues))


def generate(root: Path) -> dict[str, str]:
    """Relative path -> file content. Raises BuildError on any error issue."""
    root = Path(root)
    schema = load_schema(root)
    parts = load_parts(root, schema)
    errors = [i for i in validate(parts, schema, root) if i.severity == "error"]
    if errors:
        raise BuildError(errors)
    try:
        sources = load_source_symbols(root)
    except ValueError as e:
        raise BuildError([Issue("error", None, str(e))]) from e

    out: dict[str, str] = {}
    issues: list[Issue] = []
    for cat in schema.categories.values():
        cat_parts = [p for p in parts if p.category == cat.key]
        try:
            out[f"symbols/{cat.lib_name}.kicad_sym"] = build_symbol_lib(cat, cat_parts, sources, schema)
        except ValueError as e:
            issues.append(Issue("error", None, str(e)))
    if issues:
        raise BuildError(issues)
    out["sym-lib-table"] = sym_lib_table(schema)
    out["fp-lib-table"] = fp_lib_table(root)
    return out


def build(root: Path) -> list[Path]:
    root = Path(root)
    written = []
    for rel, text in generate(root).items():
        path = root / rel
        write_text(path, text)
        written.append(path)
    return written

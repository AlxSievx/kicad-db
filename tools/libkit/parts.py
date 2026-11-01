"""Loading and validating part data (parts/<category>.yaml)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from .schema import Category, FieldDef, Schema

_KIND_PATTERNS = {
    "int": r"\d+",
    "date": r"\d{4}-\d{2}-\d{2}",
    "url": r"https?://\S+",
}


@dataclass
class Part:
    name: str
    category: str
    data: dict[str, str]
    source: Path


@dataclass
class Issue:
    severity: str  # "error" | "warning"
    part: str | None
    message: str

    def __str__(self) -> str:
        return f"{self.severity.upper()} {self.part or '-'}: {self.message}"


def load_parts(root: Path, schema: Schema) -> list[Part]:
    parts: list[Part] = []
    for key in schema.categories:
        f = Path(root) / "parts" / f"{key}.yaml"
        if not f.exists():
            continue
        try:
            with open(f, encoding="utf-8") as fh:
                raw = yaml.load(fh, Loader=yaml.BaseLoader) or {}
        except yaml.YAMLError as e:
            raise ValueError(f"parts/{f.name}: invalid YAML: {e}") from e
        if not isinstance(raw, dict) or not isinstance(raw.get("parts") or [], list):
            raise ValueError(f"parts/{f.name}: expected a top-level 'parts:' list")
        for n, entry in enumerate(raw.get("parts") or [], 1):
            if not isinstance(entry, dict):
                raise ValueError(f"parts/{f.name}: entry {n} is not a mapping of fields")
            bad = [k for k, v in entry.items() if not isinstance(v, str)]
            if bad:
                raise ValueError(f"parts/{f.name}: entry {n}: field(s) {', '.join(bad)} must be plain values")
            data = dict(entry)
            parts.append(Part(name=data.get("name", ""), category=key, data=data, source=f))
    return parts


def _required(f: FieldDef, cat: Category) -> bool:
    if f.required == "true":
        return True
    if f.required == "orderable":
        return cat.orderable
    if f.required == "no_template":
        return cat.description_template is None
    return False


def _check_value(f: FieldDef, value: str) -> str | None:
    if f.kind == "enum" and value not in (f.choices or []):
        return f"{f.key}: {value!r} is not one of {', '.join(f.choices or [])}"
    pat = f.pattern or _KIND_PATTERNS.get(f.kind)
    if pat and not re.fullmatch(pat, value):
        return f"{f.key}: {value!r} is not a valid {f.kind if not f.pattern else 'value'}"
    return None


def validate(parts: list[Part], schema: Schema, root: Path | None = None) -> list[Issue]:
    issues: list[Issue] = []
    seen: dict[str, Path] = {}
    if root is not None:
        for f in sorted((Path(root) / "parts").glob("*.yaml")):
            if f.stem not in schema.categories:
                issues.append(Issue("error", None, f"parts/{f.name}: no such category"))
    for p in parts:
        cat = schema.categories.get(p.category)
        if cat is None:
            issues.append(Issue("error", p.name, f"unknown category {p.category!r}"))
            continue
        defs = schema.fields_for(cat)
        known = {f.key for f in defs}
        for k in p.data:
            if k not in known:
                issues.append(Issue("error", p.name, f"unknown field {k!r}"))
        for f in defs:
            v = p.data.get(f.key, "")
            if not v:
                if _required(f, cat):
                    issues.append(Issue("error", p.name, f"missing required field {f.key!r}"))
                continue
            msg = _check_value(f, v)
            if msg:
                issues.append(Issue("error", p.name, msg))
        if p.name:
            if p.name in seen:
                issues.append(Issue("error", p.name, f"duplicate name (also in {seen[p.name].name})"))
            else:
                seen[p.name] = p.source
        # The known-manufacturer rule is for automatically picked passives
        # (categories with a value unit); single parts may come from anyone.
        man = p.data.get("manufacturer")
        if cat.value_unit and man and man not in schema.manufacturers:
            issues.append(Issue("warning", p.name, f"manufacturer {man!r} not in known list"))
    return issues

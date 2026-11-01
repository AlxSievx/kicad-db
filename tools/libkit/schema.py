"""Library schema: categories, fields, footprint families (schema/library.yaml)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

SCHEMA_FILE = Path("schema") / "library.yaml"
KINDS = {"str", "enum", "url", "date", "int"}
REQUIRED_MODES = {"true", "false", "orderable", "no_template"}


@dataclass
class FieldDef:
    key: str
    label: str | None = None
    required: str = "false"  # one of REQUIRED_MODES
    kind: str = "str"
    choices: list[str] | None = None
    keyword: bool = False
    pattern: str | None = None


@dataclass
class Category:
    key: str
    title: str
    lib_name: str
    value_unit: str | None = None
    orderable: bool = True
    description_template: str | None = None
    fields: list[FieldDef] = field(default_factory=list)


@dataclass
class Family:
    name: str
    lib_name: str
    jlc_rotation: float | None = None


@dataclass
class Manufacturer:
    name: str
    aliases: list[str] = field(default_factory=list)
    # MPN prefixes that identify the maker when JLC leaves the brand empty ("--")
    mpn_prefixes: list[str] = field(default_factory=list)


@dataclass
class Schema:
    prefix: str
    common: list[FieldDef]
    categories: dict[str, Category]
    families: dict[str, Family]
    manufacturers: list[Manufacturer]

    def fields_for(self, category: Category) -> list[FieldDef]:
        return self.common + category.fields

    def canonical_manufacturer(self, brand: str, mpn: str = "") -> str | None:
        """The known manufacturer a distributor brand string means, or None.

        Matches case-insensitively when the brand equals the name or an alias,
        or starts with the name followed by a space or "(" — so
        "UNI-ROYAL(Uniroyal Elec)" is UNI-ROYAL but "FHX" is not FH.
        """
        b = brand.strip().casefold()
        if b in ("", "-", "--"):
            m_up = mpn.strip().upper()
            for m in self.manufacturers:
                if m_up and any(m_up.startswith(p.upper()) for p in m.mpn_prefixes):
                    return m.name
            return None
        for m in self.manufacturers:
            n = m.name.casefold()
            if b == n or b in (a.casefold() for a in m.aliases):
                return m.name
            if b.startswith(n) and b[len(n)] in " (":
                return m.name
        return None


def _flag(v) -> bool:
    return str(v).lower() == "true"


def _field(d: dict) -> FieldDef:
    f = FieldDef(
        key=d["key"],
        label=d.get("label"),
        required=str(d.get("required", "false")).lower(),
        kind=d.get("kind", "str"),
        choices=d.get("choices"),
        keyword=_flag(d.get("keyword", "false")),
        pattern=d.get("pattern"),
    )
    if f.kind not in KINDS:
        raise ValueError(f"field {f.key}: unknown kind {f.kind!r}")
    if f.required not in REQUIRED_MODES:
        raise ValueError(f"field {f.key}: unknown required mode {f.required!r}")
    return f


def _manufacturer(m) -> Manufacturer:
    if isinstance(m, str):
        return Manufacturer(m)
    return Manufacturer(m["name"], list(m.get("aliases") or []), list(m.get("mpn_prefixes") or []))


def load_schema(root: Path) -> Schema:
    # BaseLoader: every scalar stays a string (no 0402 -> 402 surprises).
    with open(Path(root) / SCHEMA_FILE, encoding="utf-8") as fh:
        raw = yaml.load(fh, Loader=yaml.BaseLoader)
    prefix = raw["prefix"]
    cats: dict[str, Category] = {}
    for c in raw["categories"]:
        cat = Category(
            key=c["key"],
            title=c["title"],
            lib_name=f"{prefix}_{c['title']}",
            value_unit=c.get("value_unit"),
            orderable=_flag(c.get("orderable", "true")),
            description_template=c.get("description_template"),
            fields=[_field(f) for f in c.get("fields", [])],
        )
        if cat.key in cats:
            raise ValueError(f"duplicate category {cat.key}")
        cats[cat.key] = cat
    fams = {}
    for f in raw.get("families", []):
        rot = f.get("jlc_rotation")
        fams[f["name"]] = Family(f["name"], f"{prefix}_{f['name']}", float(rot) if rot else None)
    return Schema(
        prefix=prefix,
        common=[_field(f) for f in raw["common_fields"]],
        categories=cats,
        families=fams,
        manufacturers=[_manufacturer(m) for m in raw.get("manufacturers", [])],
    )

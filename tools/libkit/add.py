"""Single-part add (spec §6.7): `libkit add <C-number|MPN>`.

prepare() is the dry run. It resolves the part at JLC, builds its YAML entry,
and stages a new symbol, footprint and 3D model under
.libkit/add/<REF>/files/<destination path>. It runs KLC on what it staged,
saves the plan, and never touches the library.

apply() is --write. It copies exactly the staged plan into the library, with
no network access, then builds. On any failure it restores every file it
touched and removes every file and folder it created.

Sources: chip passives (0402–1206 R, C, L, ferrite beads) always use the base
symbols and LIB_Passives_SMD. Anything else takes its symbol and footprint
from EasyEDA (normalised), from KiCad's stock library ("stock:<Lib>:<Name>"),
or from what LIB already has.
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import importer, jlc
from .build import build
from .datasheet import Checker
from .discretes import Discrete, classify
from .entries import KINDS, POLAR, NAME_CHARS, _attr, is_chip, kind_of, manufacturer_name, mpn_name, passive_entry
from .jlc import JlcPart, datasheet_url
from .kicad import find_kicad_cli, kicad_share
from .klc import run_klc
from .normfp import normalize_footprint
from .normsym import normalize_symbol
from .parts import Part, declare_family, load_parts, validate, write_category
from .pins import footprint_pads, symbol_pins
from .schema import Family, load_schema
from .sexpr import Sym, dumps, find, find_all, parse
from .symgen import SYM_VERSION, build_symbol_lib, load_source_symbols, write_text
from .vendor import stock_symbol, vendor_footprint

STAGE_ROOT = Path(".libkit") / "add"
PLAN_MAX_AGE = timedelta(hours=24)
LOW_STOCK = 100  # rule 2: single parts warn below ~100
CHECKLIST = "check: pinout vs datasheet · pad sizes vs land pattern · 3D model alignment"


@dataclass
class AddPlan:
    ref: str
    options: dict
    category: str
    entry: dict
    symbol: str | None  # the staged unique symbol (s-expression text), if any
    files: dict[str, str]  # repo-relative destination -> path below the staging "files" folder
    new_family: str | None
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    klc: list[str] = field(default_factory=list)
    previews: list[str] = field(default_factory=list)
    created: str = ""


def stage_dir(root: Path, ref: str) -> Path:
    return Path(root) / STAGE_ROOT / mpn_name(ref.strip().upper())


def _options(**kw) -> dict:
    return json.loads(json.dumps(kw))


def _describe(part: JlcPart) -> str:
    text = re.sub(r"\s+ROHS$", "", part.description.strip(), flags=re.I).strip()
    text = text.replace("℃", "°C").replace("、", ", ")
    return " ".join(text.split()) or part.mpn


def _valid_name(name: str, what: str) -> str:
    if not name or NAME_CHARS.search(name):
        raise ValueError(f"{what} {name!r}: only letters, digits and _ - . + , are allowed (KLC G1.1)")
    return name


class _Stage:
    """The staging folder of one plan: files/<repo-relative path> mirror the destinations."""

    def __init__(self, root: Path, ref: str):
        self.root = Path(root)
        self.dir = stage_dir(root, ref)
        if self.dir.exists():
            shutil.rmtree(self.dir)
        self.files_dir = self.dir / "files"
        self.files_dir.mkdir(parents=True)
        self.files: dict[str, str] = {}

    def put_text(self, rel: str, text: str) -> Path:
        path = self.files_dir / rel
        write_text(path, text)
        self.files[rel] = rel
        return path

    def put_file(self, rel: str, src: Path) -> None:
        path = self.files_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, path)
        self.files[rel] = rel


def _footprint(stage: _Stage, schema, part: JlcPart, choice: str, family: str | None, fp_name: str | None,
               fetched, notes: list[str], share: Path) -> tuple[str, str | None]:
    """(footprint reference for the entry, new family to declare or None)."""
    root = stage.root
    if choice != "easyeda" and not choice.startswith("stock:"):
        lib, _, name = choice.partition(":")
        if not name or not (root / "footprints" / f"{lib}.pretty" / f"{name}.kicad_mod").exists():
            raise ValueError(f"footprint {choice!r} does not exist in footprints/")
        return choice, None
    if not family:
        raise ValueError("--family is required for a new footprint (e.g. Package_TO_SOT, Inductor_SMD)")
    _valid_name(family, "family")
    fam = schema.families.get(family) or Family(family, f"{schema.prefix}_{family}")
    new_family = None if family in schema.families else family
    pretty = f"footprints/{fam.lib_name}.pretty"

    if choice.startswith("stock:"):
        stock_ref = choice.removeprefix("stock:")
        name = stock_ref.partition(":")[2]
        if (root / pretty / f"{name}.kicad_mod").exists():
            notes.append(f"reusing existing footprint {fam.lib_name}:{name}")
            return f"{fam.lib_name}:{name}", new_family
        tmp = stage.dir / "stock"
        out = vendor_footprint(stock_ref, fam, root, share, dest_dir=tmp / "fp", models_dir=tmp / "3d")
        stage.put_file(f"{pretty}/{out.name}", out)
        for model in sorted((tmp / "3d").glob("*")):
            stage.put_file(f"3dmodels/{fam.lib_name}.3dshapes/{model.name}", model)
        return f"{fam.lib_name}:{name}", new_family

    if fetched is None or fetched.footprint is None:
        raise ValueError(f"{part.lcsc}: EasyEDA has no footprint for this part")
    name = _valid_name(fp_name or mpn_name(fetched.footprint_name or part.mpn), "--fp-name")
    if (root / pretty / f"{name}.kicad_mod").exists():
        notes.append(f"reusing existing footprint {fam.lib_name}:{name}")
        return f"{fam.lib_name}:{name}", new_family
    model = f"{name}.step" if fetched.step else None
    fp, fp_notes = normalize_footprint(
        fetched.footprint, name=name, lib=fam.lib_name, model=model,
        description=f"{_describe(part)}, {datasheet_url(part)} (EasyEDA {part.lcsc})",
        tags=" ".join(dict.fromkeys(t for t in re.split(r"[\s,]+", f"{part.package} {part.mpn}") if t)))
    notes += fp_notes
    stage.put_text(f"{pretty}/{name}.kicad_mod", dumps(fp))
    if fetched.step:
        stage.put_file(f"3dmodels/{fam.lib_name}.3dshapes/{model}", fetched.step)
    return f"{fam.lib_name}:{name}", new_family


def _footprint_file(stage: _Stage, fp_ref: str) -> Path:
    """The staged footprint file of `fp_ref`, else the library's."""
    lib, _, name = fp_ref.partition(":")
    rel = f"footprints/{lib}.pretty/{name}.kicad_mod"
    return stage.files_dir / rel if rel in stage.files else stage.root / rel


def _default_symbol(disc: Discrete | None, fp_file: Path, notes: list[str]) -> str:
    """The discrete base symbol when the footprint's pads fit it, else "easyeda"."""
    if disc is None:
        return "easyeda"
    if disc.symbol is None:
        notes.append(f"no base symbol: {disc.why}")
        return "easyeda"
    pads = footprint_pads(fp_file)
    if pads != disc.pads:
        order = sorted(pads, key=lambda n: (not n.isdigit(), int(n) if n.isdigit() else 0, n))
        notes.append(f"base {disc.symbol} does not fit pads {', '.join(order)}: EasyEDA symbol")
        return "easyeda"
    notes.append(f"base symbol {disc.symbol}; check: {disc.checklist}")
    return disc.symbol


def _entry(part: JlcPart, kind: str | None, schema, footprint: str, name: str | None,
           today: date | None) -> dict[str, str]:
    if kind:  # R, C, L or bead in a package other than 0402–1206: named by MPN
        entry = passive_entry(kind, part, schema, today, footprint=footprint, known_only=False)
        if name:
            entry["name"] = name
        return entry
    manufacturer, _ = manufacturer_name(part.brand, schema, part.mpn)
    return {
        "name": name or mpn_name(part.mpn),
        "symbol": "",
        "footprint": footprint,
        "value": part.mpn,
        "package": part.package,
        "description": _describe(part),
        "manufacturer": manufacturer,
        "mpn": part.mpn,
        "lcsc": part.lcsc,
        "jlc_type": part.jlc_type,
        "datasheet": datasheet_url(part),
        "status": "active",
        "stock": str(part.stock),
        "stock_checked": (today or date.today()).isoformat(),
    }


def _klc(stage: _Stage, schema, category: str, entry: dict, unique: list | None) -> list[str]:
    root = stage.root
    sources = load_source_symbols(root)
    if unique is not None:
        sources[entry["name"]] = unique
    cat = schema.categories[category]
    lib_file = stage.dir / "klc" / f"{cat.lib_name}.kicad_sym"
    write_text(lib_file, build_symbol_lib(cat, [Part(entry["name"], category, entry, lib_file)], sources, schema))
    targets = [lib_file] + [stage.files_dir / rel for rel in stage.files if rel.endswith(".kicad_mod")]
    return [str(i) for i in run_klc(root, targets)]


def _previews(stage: _Stage) -> list[str]:
    import subprocess
    cli = find_kicad_cli()
    if cli is None:
        return []
    out = stage.dir / "preview"
    out.mkdir(exist_ok=True)
    jobs = [("sym", f) for f in (stage.dir / "klc").glob("*.kicad_sym")]
    jobs += [("fp", d) for d in (stage.files_dir / "footprints").glob("*.pretty")]
    for kind, src in jobs:
        subprocess.run([str(cli), kind, "export", "svg", str(src), "-o", str(out)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return [str(p) for p in sorted(out.glob("*.svg"))]


def prepare(root: Path, ref: str, *, category: str | None = None, symbol: str | None = None,
            footprint: str | None = None, family: str | None = None, fp_name: str | None = None,
            name: str | None = None, pin_types: dict[str, str] | None = None, resolve=None, fetch=None,
            lang=None, klc: bool = True, previews: bool = False, kicad_share_dir: Path | None = None,
            today: date | None = None) -> AddPlan:
    root = Path(root)
    options = _options(category=category, symbol=symbol, footprint=footprint, family=family, fp_name=fp_name,
                       name=name, pin_types=pin_types)
    schema = load_schema(root)
    library = load_parts(root, schema)
    by_lcsc = {p.data.get("lcsc"): p.name for p in library if p.data.get("lcsc")}
    names = {p.name: p.data.get("status", "?") for p in library}

    part = (resolve or jlc.resolve)(ref)
    if part.lcsc in by_lcsc:
        raise ValueError(f"{part.lcsc} is already in the library as {by_lcsc[part.lcsc]}")
    if part.stock <= 0:
        raise ValueError(f"{part.lcsc}: out of stock at JLC (rule 2: stock > 0)")
    warnings, notes = [], []
    if part.stock < LOW_STOCK:
        warnings.append(f"low stock {part.stock}")
    if part.jlc_type == "Extended":
        notes.append("Extended part")

    kind = kind_of(part)
    stage = _Stage(root, ref)
    unique = None
    new_family = None
    from .polar import size_of
    chip = kind is not None and (size_of(kind, part) is not None if kind in POLAR else is_chip(kind, part.package))
    if chip:
        given = [k for k in ("category", "symbol", "footprint", "family", "fp_name", "name", "pin_types")
                 if options[k]]
        if given:
            raise ValueError(f"{part.lcsc} is a chip {kind}: it always uses the base symbol and "
                             f"LIB_Passives_SMD, so --{given[0].replace('_', '-')} does not apply")
        category = KINDS[kind][0]
        entry = passive_entry(kind, part, schema, today, known_only=False)
        lib, _, fp = entry["footprint"].partition(":")
        if not (root / "footprints" / f"{lib}.pretty" / f"{fp}.kicad_mod").exists():
            raise ValueError(f"footprint {entry['footprint']} is not in the library yet — vendor it first "
                             "(libkit vendor-fp)")
    else:
        disc = None if kind else classify(part)
        category = category or (KINDS[kind][0] if kind else disc.category if disc else None)
        if category not in schema.categories:
            raise ValueError(f"--category is required: one of {', '.join(schema.categories)}")
        symbol = symbol or (KINDS[kind][1] if kind else None)  # None: decided by the footprint's pads
        footprint = footprint or "easyeda"
        share = Path(kicad_share_dir) if kicad_share_dir else kicad_share()
        fetched = None

        def easyeda():
            nonlocal fetched
            if fetched is None:
                fetched = (fetch or importer.fetch_easyeda)(part.lcsc, stage.dir / "easyeda")
            return fetched

        if footprint == "easyeda":
            easyeda()
        fp_ref, new_family = _footprint(stage, schema, part, footprint, family, fp_name, fetched, notes, share)
        fp_file = _footprint_file(stage, fp_ref)
        if symbol is None:
            symbol = _default_symbol(disc, fp_file, notes)
        if pin_types and symbol != "easyeda":
            raise ValueError("--pin-types applies to EasyEDA symbols only")
        if symbol == "easyeda":
            easyeda()
        entry = _entry(part, kind, schema, fp_ref, name, today)
        if category == "inductors" and not kind:  # e.g. common-mode chokes: fields from JLC's record
            for key, attr in (("current_rating", "Current Rating"), ("dcr", "DC Resistance(DCR)")):
                value = _attr(part, attr, required=False)
                if value and key not in entry:
                    entry[key] = "".join(value.split())
        if disc:
            declared = {f.key for f in schema.categories[category].fields}
            entry.update({k: v for k, v in disc.fields.items() if k in declared and k not in entry})
        _valid_name(entry["name"], "part name")
        sources = load_source_symbols(root)
        if symbol == "easyeda":
            if fetched is None or fetched.symbol is None:
                raise ValueError(f"{part.lcsc}: EasyEDA has no symbol for this part")
            unique, sym_notes = normalize_symbol(fetched.symbol, entry["name"], pin_types)
            notes += sym_notes
        elif symbol.startswith("stock:"):
            unique = stock_symbol(symbol.removeprefix("stock:"), share, entry["name"])
        elif symbol not in sources:
            raise ValueError(f"symbol {symbol!r} is not in src/symbols")
        if unique is not None:
            if entry["name"] in sources:
                raise ValueError(f"a source symbol named {entry['name']!r} already exists in src/symbols")
            entry["symbol"] = entry["name"]
        else:
            entry["symbol"] = symbol
        all_syms = {**sources, entry["name"]: unique} if unique is not None else sources
        missing = symbol_pins(entry["symbol"], all_syms) - footprint_pads(fp_file)
        if missing:
            raise ValueError(f"{entry['name']} would fail check: symbol pin(s) {', '.join(sorted(missing))} "
                             f"have no pad in {fp_ref}")

    if entry["name"] in names:
        raise ValueError(f"part name {entry['name']} is already in the library ({names[entry['name']]})")
    bad = [i.message for i in validate([Part(entry["name"], category, entry, Path("new"))], schema)
           if i.severity == "error"]
    if bad:
        raise ValueError(f"{entry['name']} would not build in {category}: {'; '.join(bad)}")
    manufacturer, known = manufacturer_name(part.brand, schema, part.mpn)
    if not known:
        warnings.append(f"manufacturer {manufacturer!r} (JLC: {part.brand!r}) is not in manufacturers: — kept "
                        "for this single add")
    if lang is not None:
        ds = lang(part)
        entry["datasheet_lang"] = ds.lang
        if ds.lang == "zh":
            warnings.append("no English datasheet")
        elif ds.lang == "unknown":
            notes.append(f"datasheet language unknown ({ds.note})" if ds.note else "datasheet language unknown")

    plan = AddPlan(ref=ref, options=options, category=category, entry=entry,
                   symbol=dumps(unique) if unique is not None else None, files=dict(stage.files),
                   new_family=new_family, warnings=warnings, notes=notes)
    return _save(stage, schema, plan, unique, klc, previews)


def _save(stage: _Stage, schema, plan: AddPlan, unique: list | None, klc: bool, previews: bool) -> AddPlan:
    if klc:
        plan.klc = _klc(stage, schema, plan.category, plan.entry, unique)
        if previews:
            plan.previews = _previews(stage)
    plan.created = datetime.now(timezone.utc).isoformat(timespec="seconds")
    (stage.dir / "plan.json").write_text(json.dumps(asdict(plan), indent=1, ensure_ascii=False), encoding="utf-8")
    return plan


LOCAL_SYMBOLS = {"MountingHole": "MountingHole", "Fiducial": "Fiducial", "TestPoint": "TestPoint"}


def local_symbol(footprint_ref: str) -> str | None:
    """The mechanical base symbol for a stock or LIB footprint reference, if obvious."""
    lib, _, name = footprint_ref.removeprefix("stock:").partition(":")
    lib = lib.removeprefix("LIB_")
    if lib == "MountingHole":
        return "MountingHole_Pad" if "_Pad" in name else "MountingHole"
    return LOCAL_SYMBOLS.get(lib)


def local_options(**kw) -> dict:
    return _options(local=True, **kw)


def prepare_local(root: Path, name: str, *, category: str, footprint: str, family: str | None = None,
                  symbol: str | None = None, value: str | None = None, description: str | None = None,
                  klc: bool = True, previews: bool = False, kicad_share_dir: Path | None = None) -> AddPlan:
    """Dry run for a part without a C-number (category with orderable: false); no network."""
    root = Path(root)
    options = local_options(category=category, symbol=symbol, footprint=footprint, family=family, value=value,
                            description=description)
    schema = load_schema(root)
    if category not in schema.categories:
        raise ValueError(f"unknown category {category!r}; one of {', '.join(schema.categories)}")
    if schema.categories[category].orderable:
        raise ValueError(f"--local is for non-orderable categories (e.g. mechanical); {category} parts need a "
                         "C-number")
    if footprint == "easyeda":
        raise ValueError("--local parts have no C-number: use a stock: or LIB_ footprint")
    _valid_name(name, "part name")
    names = {p.name: p.data.get("status", "?") for p in load_parts(root, schema)}
    if name in names:
        raise ValueError(f"part name {name} is already in the library ({names[name]})")
    symbol = symbol or local_symbol(footprint)
    if not symbol:
        raise ValueError(f"no default symbol for {footprint}: give --symbol (a base in src/symbols or "
                         "stock:<Lib>:<Name>)")
    stage = _Stage(root, name)
    notes: list[str] = []
    share = Path(kicad_share_dir) if kicad_share_dir else kicad_share()
    fp_ref, new_family = _footprint(stage, schema, None, footprint, family, None, None, notes, share)
    fp_file = _footprint_file(stage, fp_ref)
    descr = find(parse(fp_file.read_text(encoding="utf-8")), "descr")
    description = description or (str(descr[1]).strip() if descr is not None else "")
    if not description:
        raise ValueError(f"{fp_ref} has no description: give --description")
    sources = load_source_symbols(root)
    unique = None
    if symbol.startswith("stock:"):
        unique = stock_symbol(symbol.removeprefix("stock:"), share, name)
        if name in sources:
            raise ValueError(f"a source symbol named {name!r} already exists in src/symbols")
    elif symbol not in sources:
        raise ValueError(f"symbol {symbol!r} is not in src/symbols")
    entry = {"name": name, "symbol": name if unique is not None else symbol, "footprint": fp_ref,
             "value": value or name, "package": fp_ref.partition(":")[2], "description": description,
             "status": "active"}
    all_syms = {**sources, name: unique} if unique is not None else sources
    missing = symbol_pins(entry["symbol"], all_syms) - footprint_pads(fp_file)
    if missing:
        raise ValueError(f"{name} would fail check: symbol pin(s) {', '.join(sorted(missing))} have no pad in "
                         f"{fp_ref}")
    bad = [i.message for i in validate([Part(name, category, entry, Path("new"))], schema) if i.severity == "error"]
    if bad:
        raise ValueError(f"{name} would not build in {category}: {'; '.join(bad)}")
    plan = AddPlan(ref=name, options=options, category=category, entry=entry,
                   symbol=dumps(unique) if unique is not None else None, files=dict(stage.files),
                   new_family=new_family, notes=notes)
    return _save(stage, schema, plan, unique, klc, previews)


def load_plan(root: Path, ref: str, options: dict, now: datetime | None = None) -> AddPlan:
    """The saved dry run for `ref`, if it may still be applied as it is."""
    rerun = "run the same command without --write first"
    path = stage_dir(root, ref) / "plan.json"
    try:
        plan = AddPlan(**json.loads(path.read_text(encoding="utf-8")))
    except FileNotFoundError:
        raise ValueError(f"no dry run for {ref} to apply: {rerun}") from None
    except (OSError, ValueError, TypeError) as e:
        raise ValueError(f"the dry run for {ref} is unreadable ({e}): {rerun}") from None
    if plan.options != _options(**options):
        raise ValueError(f"the dry run for {ref} was made with other options: {rerun}")
    age = (now or datetime.now(timezone.utc)) - datetime.fromisoformat(plan.created)
    if age > PLAN_MAX_AGE:
        raise ValueError(f"the dry run for {ref} is older than {PLAN_MAX_AGE.total_seconds() / 3600:g} h: {rerun}")
    schema = load_schema(root)
    for p in load_parts(root, schema):
        if p.name == plan.entry["name"] or (p.data.get("lcsc") and p.data.get("lcsc") == plan.entry.get("lcsc")):
            raise ValueError(f"{plan.entry['name']} ({plan.entry.get('lcsc')}) is already in the library as "
                             f"{p.name}: {rerun}")
    staged = stage_dir(root, ref) / "files"
    for rel in plan.files:
        dest = Path(root) / rel
        if not (staged / rel).exists():
            raise ValueError(f"staged file {rel} is missing: {rerun}")
        if dest.exists() and dest.read_bytes() != (staged / rel).read_bytes():
            raise ValueError(f"{rel} exists with other content: {rerun}")
    return plan


class _Undo:
    """Remembers files before they change, and folders that did not exist."""

    def __init__(self):
        self.saved: dict[Path, bytes | None] = {}
        self.dirs: list[Path] = []

    def touch(self, path: Path) -> Path:
        if path not in self.saved:
            self.saved[path] = path.read_bytes() if path.exists() else None
        missing = []
        d = path.parent
        while not d.exists():
            missing.append(d)
            d = d.parent
        self.dirs += reversed(missing)
        return path

    def rollback(self) -> None:
        for path, data in self.saved.items():
            if data is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(data)
        for d in reversed(self.dirs):
            if d.exists() and not any(d.iterdir()):
                d.rmdir()


def _append_symbol(path: Path, text: str) -> None:
    if path.exists():
        lib = parse(path.read_text(encoding="utf-8"))
    else:
        lib = [Sym("kicad_symbol_lib"), [Sym("version"), Sym(SYM_VERSION)],
               [Sym("generator"), "libkit"], [Sym("generator_version"), "1.0"]]
    lib.append(parse(text))
    write_text(path, dumps(lib))


def apply(root: Path, plan: AddPlan) -> list[Path]:
    """Write a loaded plan into the library and build; all or nothing."""
    root = Path(root)
    staged = stage_dir(root, plan.ref) / "files"
    undo = _Undo()
    written: list[Path] = []
    try:
        if plan.new_family:
            undo.touch(root / "schema" / "library.yaml")
            declare_family(root, plan.new_family)
            written.append(root / "schema" / "library.yaml")
        for rel in plan.files:
            dest = undo.touch(root / rel)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(staged / rel, dest)
            written.append(dest)
        if plan.symbol:
            src = undo.touch(root / "src" / "symbols" / f"{plan.category}.kicad_sym")
            _append_symbol(src, plan.symbol)
            written.append(src)
        schema = load_schema(root)
        yaml_file = undo.touch(root / "parts" / f"{plan.category}.yaml")
        old = [p.data for p in load_parts(root, schema) if p.category == plan.category]
        write_category(root, plan.category, old + [plan.entry])
        written.append(yaml_file)
        for f in [*sorted((root / "symbols").glob("*.kicad_sym")), root / "sym-lib-table", root / "fp-lib-table"]:
            undo.touch(f)
        cat = schema.categories[plan.category]
        undo.touch(root / "symbols" / f"{cat.lib_name}.kicad_sym")
        build(root)
    except BaseException:
        undo.rollback()
        raise
    return written


def clear_plan(root: Path, ref: str) -> None:
    shutil.rmtree(stage_dir(root, ref), ignore_errors=True)

"""Part names and complete YAML entries for passives picked at JLC."""

from __future__ import annotations

import re
from datetime import date

from .jlc import JlcPart, datasheet_url
from .schema import Schema
from .values import format_value, parse_value

KINDS = {
    # kind: (category, symbol, value unit, footprint prefix)
    "resistor": ("resistors", "R", "Ω", "R"),
    "capacitor": ("capacitors", "C", "F", "C"),
    "inductor": ("inductors", "L", "H", "L"),
    "bead": ("inductors", "FerriteBead", "Ω", "L"),  # value unit: impedance
    "tantalum": ("capacitors", "C_Polarized", "F", "CP"),
    "electrolytic": ("capacitors", "C_Polarized", "F", "CP"),
}
POLAR = {"tantalum": "Ta", "electrolytic": "Al"}  # kind: dielectric field
NAME_CHARS = re.compile(r"[^A-Za-z0-9_.+,-]+")  # KLC G1.1
METRIC = {"0402": "1005", "0603": "1608", "0805": "2012", "1206": "3216", "1210": "3225", "2512": "6332"}
# Chip sizes with a LIB_Passives_SMD footprint, per kind (a 1210 inductor is not a chip part).
_BASE = {"0402", "0603", "0805", "1206"}
CHIP_SIZES = {"resistor": _BASE | {"2512"}, "capacitor": _BASE | {"1210"}, "inductor": _BASE, "bead": _BASE}


def is_chip(kind: str, package: str) -> bool:
    return package in CHIP_SIZES.get(kind, ())


def _kind(kind: str):
    if kind not in KINDS:
        raise ValueError(f"unknown passive kind {kind!r}; known: {', '.join(KINDS)}")
    return KINDS[kind]


def passive_name(kind: str, value: float, package: str, *, tolerance: float | None = None,
                 voltage: float | None = None, dielectric: str | None = None,
                 current: str | None = None) -> str:
    """R_<value>_<pkg>_<tol>pct, C_<value w/o F>_<pkg>_<voltage>_<dielectric>,
    L_<value w/o H>_<pkg>_<current> or FB_<impedance>_<pkg>_<current> (CLAUDE.md)."""
    _, _, unit, prefix = _kind(kind)
    if kind in ("inductor", "bead"):
        if not current:
            raise ValueError(f"an {kind} name needs a current rating")
        text = format_value(value, unit)
        return (f"L_{text[:-1]}" if kind == "inductor" else f"FB_{text}") + f"_{package}_{current}"
    if kind == "resistor":
        if tolerance is None:
            raise ValueError("a resistor name needs a tolerance")
        return f"R_{format_value(value, unit)}_{package}_{tolerance * 100:g}pct"
    if voltage is None or not dielectric:
        raise ValueError("a capacitor name needs a voltage and a dielectric")
    return f"C_{format_value(value, unit)[:-1]}_{package}_{voltage:g}V_{dielectric}"


def footprint_for(kind: str, package: str) -> str:
    _, _, _, prefix = _kind(kind)
    if not is_chip(kind, package):
        raise ValueError(f"no {kind} footprint for package {package!r}; known: "
                         f"{', '.join(sorted(CHIP_SIZES.get(kind, ())))}")
    return f"LIB_Passives_SMD:{prefix}_{package}_{METRIC[package]}Metric"


def _clean(text: str) -> str:
    return text.strip().replace("℃", "°C")


def _key(name: str) -> str:
    return "".join(name.split()).casefold()


def _attr(part: JlcPart, *keys: str, required: bool = True) -> str:
    """The first of `keys` the record has a value for. Attribute names match
    with whitespace removed and case folded (JLC writes "Current - Saturation
    (Isat)" and "Current - Saturation(Isat)"); "-" means no value."""
    by_key = {_key(k): v for k, v in part.attributes.items()}
    for key in keys:
        v = _clean(by_key.get(_key(key), ""))
        if v and v != "-":
            return v
    if required:
        raise ValueError(f"{part.lcsc}: JLC record has no {keys[0]!r} attribute")
    return ""


def _has(part: JlcPart, key: str) -> bool:
    return bool(_attr(part, key, required=False))


def kind_of(part: JlcPart) -> str | None:
    """The passive kind a JLC record describes, or None (also for arrays)."""
    if _array(part):
        return None
    from .polar import ELECTROLYTIC_TYPE, TANTALUM_TYPE
    if part.type_name == TANTALUM_TYPE:
        return "tantalum"
    if part.type_name == ELECTROLYTIC_TYPE:
        return "electrolytic"
    if "common mode" in part.type_name.casefold():
        return None  # multi-line chokes: single add with a coupled-inductor symbol
    if "electrolytic" in part.type_name.casefold() or "polymer" in part.type_name.casefold():
        return None  # hybrid / polymer aluminium: no bulk kind (single add by MPN only)
    for key, kind in (("Resistance", "resistor"), ("Capacitance", "capacitor"),
                      ("Impedance @ Frequency", "bead"), ("Inductance", "inductor")):
        if _has(part, key):
            return kind
    return None


def mpn_name(mpn: str) -> str:
    """A part name from an MPN: each run of characters KLC G1.1 does not allow becomes "_"."""
    name = NAME_CHARS.sub("_", mpn.strip()).strip("_")
    if not name:
        raise ValueError(f"MPN {mpn!r} gives no usable part name")
    return name


def manufacturer_name(brand: str, schema: Schema, mpn: str = "") -> tuple[str, bool]:
    """(canonical name, True) for a known manufacturer, else (the brand without
    a "(…)" suffix, False) — single adds may come from anyone (rule 3 is for picks)."""
    known = schema.canonical_manufacturer(brand, mpn)
    if known:
        return known, True
    return re.sub(r"\s*\(.*\)\s*$", "", brand).strip() or brand.strip(), False


def _compact(text: str) -> str:
    return "".join(text.split())


def _percent(text: str, lcsc: str) -> float:
    m = re.fullmatch(r"±?\s*(\d+(?:\.\d+)?)\s*%", text)
    if not m:
        raise ValueError(f"{lcsc}: tolerance {text!r} is not a percentage")
    return float(m.group(1)) / 100


def _volts(text: str, lcsc: str) -> float:
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(k?)V", text)
    if not m:
        raise ValueError(f"{lcsc}: voltage {text!r} not understood")
    return float(m.group(1)) * (1000 if m.group(2) else 1)


def _array(part: JlcPart) -> str | None:
    """Why `part` is a network/array (several elements, more than two pins), or None.
    JLC lists arrays under the same package name ("1206") as single chips."""
    for key in ("Number of Resistors", "Number of Capacitors", "Number of Pins"):
        m = re.match(r"\d+", part.attributes.get(key, "").strip())
        if m and int(m.group()) > (2 if key == "Number of Pins" else 1):
            return f"{key.lower()} {m.group()}"
    if re.search(r"\b(networks?|arrays?)\b", part.description, re.I):
        return "network/array"
    return None


def _value(kind: str, part: JlcPart) -> tuple[float, str]:
    """(value in the kind's unit, test frequency for beads or "")."""
    unit = _kind(kind)[2]
    raw = _attr(part, {"resistor": "Resistance", "capacitor": "Capacitance", "inductor": "Inductance",
                       "bead": "Impedance @ Frequency"}[kind])
    frequency = ""
    if kind == "bead":
        raw, _, frequency = raw.partition("@")
    return parse_value(_compact(raw), unit), frequency


def part_value(kind: str, part: JlcPart) -> float | None:
    """The part's resistance/capacitance/inductance/impedance, or None when JLC has none."""
    try:
        return _value(kind, part)[0]
    except ValueError:
        return None


def passive_entry(kind: str, part: JlcPart, schema: Schema, today: date | None = None, *,
                  footprint: str | None = None, known_only: bool = True) -> dict[str, str]:
    """The full YAML entry for a resistor, capacitor, inductor or ferrite bead from its JLC record.

    Chip packages (0402–1206) get the pattern name and the LIB_Passives_SMD
    footprint. Any other package needs `footprint`, and the part is named by
    its MPN. known_only=False (single adds) keeps an unknown brand instead of
    refusing it."""
    category, symbol, unit, _ = _kind(kind)
    why = _array(part)
    if why:
        raise ValueError(f"{part.lcsc}: an array, not a single two-pin part ({why})")
    if known_only:
        manufacturer = schema.canonical_manufacturer(part.brand, part.mpn)
        if manufacturer is None:
            raise ValueError(f"{part.lcsc}: manufacturer {part.brand!r} is not a known manufacturer")
    else:
        manufacturer, _ = manufacturer_name(part.brand, schema, part.mpn)
    if kind in POLAR:
        return _polar_entry(kind, part, manufacturer, today, footprint)
    chip = is_chip(kind, part.package)
    if footprint is None:
        if not chip:
            raise ValueError(f"{part.lcsc}: package {part.package!r} is not a chip package; "
                             "a footprint must be given")
        footprint = footprint_for(kind, part.package)
    value, frequency = _value(kind, part)
    value_text = format_value(value, unit) + (f"@{_compact(frequency)}" if frequency else "")
    entry = {
        "name": "",
        "symbol": symbol,
        "footprint": footprint,
        "value": value_text,
        "package": part.package,
        "manufacturer": manufacturer,
        "mpn": part.mpn,
        "lcsc": part.lcsc,
        "jlc_type": part.jlc_type,
        "datasheet": datasheet_url(part),
        "status": "active",
        "stock": str(part.stock),
        "stock_checked": (today or date.today()).isoformat(),
    }
    if kind in ("inductor", "bead"):
        current = _compact(_attr(part, "Current Rating"))
        entry["current_rating"] = current
        if kind == "inductor":
            sat = _attr(part, "Current - Saturation (Isat)", required=False)
            if sat:
                entry["current_sat"] = _compact(sat)
        dcr = _attr(part, "DC Resistance(DCR)", required=False)
        if dcr:
            entry["dcr"] = _compact(dcr)
        if kind == "bead":
            entry["description"] = f"{value_text} {current} {part.package} ferrite bead"
        entry["name"] = (passive_name(kind, value, part.package, current=current) if chip
                         else mpn_name(part.mpn))
        return entry
    tolerance = _attr(part, "Tolerance")
    if kind == "resistor":
        entry["tolerance"] = tolerance
        entry["power"] = _attr(part, "Power(Watts)")
        tempco = _clean(part.attributes.get("Temperature Coefficient", ""))
        if tempco and tempco != "-":
            entry["tempco"] = tempco
        entry["name"] = passive_name(kind, value, part.package, tolerance=_percent(tolerance, part.lcsc))
    else:
        voltage = _attr(part, "Voltage Rating")
        dielectric = _attr(part, "Temperature Coefficient")
        entry.update(voltage=voltage, dielectric=dielectric, tolerance=tolerance)
        entry["name"] = passive_name(kind, value, part.package, voltage=_volts(voltage, part.lcsc),
                                     dielectric=dielectric)
    return entry


def _polar_entry(kind: str, part: JlcPart, manufacturer: str, today: date | None,
                 footprint: str | None = None) -> dict[str, str]:
    """Tantalum or electrolytic: C_<value>_<CaseA|D6.3x7.7>_<voltage>_<Ta|Al> (plan 6).
    A case/can LIB has no footprint for needs `footprint`; the part is then named by its MPN."""
    from .polar import footprint_name, package_name, size_of
    size = size_of(kind, part)
    if size is None and footprint is None:
        raise ValueError(f"{part.lcsc}: package {part.package!r} is not a {kind} case/can LIB supports; "
                         "a footprint must be given")
    value, _ = _value("capacitor", part)
    voltage = _attr(part, "Voltage Rating")
    volts = _volts(voltage, part.lcsc)
    tolerance = _attr(part, "Tolerance")
    _percent(tolerance, part.lcsc)
    package = package_name(kind, size) if size else part.package
    text = format_value(value, "F")
    entry = {
        "name": f"C_{text[:-1]}_{package}_{volts:g}V_{POLAR[kind]}" if size else mpn_name(part.mpn),
        "symbol": "C_Polarized",
        "footprint": f"LIB_Passives_SMD:{footprint_name(kind, size)}" if size else footprint,
        "value": text,
        "package": package,
        "manufacturer": manufacturer,
        "mpn": part.mpn,
        "lcsc": part.lcsc,
        "jlc_type": part.jlc_type,
        "datasheet": datasheet_url(part),
        "status": "active",
        "stock": str(part.stock),
        "stock_checked": (today or date.today()).isoformat(),
        "voltage": voltage,
        "dielectric": POLAR[kind],
        "tolerance": tolerance,
    }
    esr = _attr(part, "Equivalent Series Resistance(ESR)", required=False)
    if esr:
        entry["esr"] = _compact(esr)
    if kind == "electrolytic":
        life = _attr(part, "Lifetime", required=False)
        if life:
            entry["lifetime"] = _compact(life)
    return entry

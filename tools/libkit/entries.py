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
}
METRIC = {"0402": "1005", "0603": "1608", "0805": "2012", "1206": "3216"}


def _kind(kind: str):
    if kind not in KINDS:
        raise ValueError(f"unknown passive kind {kind!r}; known: {', '.join(KINDS)}")
    return KINDS[kind]


def passive_name(kind: str, value: float, package: str, *, tolerance: float | None = None,
                 voltage: float | None = None, dielectric: str | None = None) -> str:
    """R_<value>_<pkg>_<tol>pct or C_<value w/o F>_<pkg>_<voltage>_<dielectric> (CLAUDE.md)."""
    _, _, unit, prefix = _kind(kind)
    if kind == "resistor":
        if tolerance is None:
            raise ValueError("a resistor name needs a tolerance")
        return f"R_{format_value(value, unit)}_{package}_{tolerance * 100:g}pct"
    if voltage is None or not dielectric:
        raise ValueError("a capacitor name needs a voltage and a dielectric")
    return f"C_{format_value(value, unit)[:-1]}_{package}_{voltage:g}V_{dielectric}"


def footprint_for(kind: str, package: str) -> str:
    _, _, _, prefix = _kind(kind)
    if package not in METRIC:
        raise ValueError(f"no footprint for package {package!r}; known: {', '.join(METRIC)}")
    return f"LIB_Passives_SMD:{prefix}_{package}_{METRIC[package]}Metric"


def _clean(text: str) -> str:
    return text.strip().replace("℃", "°C")


def _attr(part: JlcPart, key: str) -> str:
    v = _clean(part.attributes.get(key, ""))
    if not v or v == "-":
        raise ValueError(f"{part.lcsc}: JLC record has no {key!r} attribute")
    return v


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


def passive_entry(kind: str, part: JlcPart, schema: Schema, today: date | None = None) -> dict[str, str]:
    """The full YAML entry for a resistor or capacitor from its JLC record."""
    category, symbol, unit, _ = _kind(kind)
    why = _array(part)
    if why:
        raise ValueError(f"{part.lcsc}: an array, not a single two-pin part ({why})")
    manufacturer = schema.canonical_manufacturer(part.brand)
    if manufacturer is None:
        raise ValueError(f"{part.lcsc}: manufacturer {part.brand!r} is not a known manufacturer")
    value_key = "Resistance" if kind == "resistor" else "Capacitance"
    value = parse_value(_attr(part, value_key), unit)
    tolerance = _attr(part, "Tolerance")
    entry = {
        "name": "",
        "symbol": symbol,
        "footprint": footprint_for(kind, part.package),
        "value": format_value(value, unit),
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

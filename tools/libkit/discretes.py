"""Diodes, LEDs and small transistors: category, default base symbol and
category fields from a JLC record (componentTypeEn + attributes).

A base symbol is proposed only when the record says it fits: a single diode
or LED (pads 1, 2), or a single MOSFET/BJT in a SOT-23-like package whose
pinout is G/S/D or B/E/C (pads 1, 2, 3). add.py still compares the pads of
the chosen footprint before it uses the base.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .entries import _attr
from .jlc import JlcPart

SOT23_FAMILY = {"SOT-23", "SOT-23-3", "SOT-23-3L", "SOT-323", "SOT-323-3", "SC-70", "SC-70-3", "SOT-416",
                "SOT-523"}
SINGLE_CONFIG = {"", "standalone", "single", "1independent", "independent", "discretediode"}
TWO = frozenset({"1", "2"})
THREE = frozenset({"1", "2", "3"})
DIODE_CHECK = "pad 1 = cathode (K), pad 2 = anode (A)"


@dataclass
class Discrete:
    category: str
    symbol: str | None
    pads: frozenset[str]
    fields: dict[str, str] = field(default_factory=dict)
    checklist: str = ""
    why: str = ""  # why there is no default symbol


def _fold(text: str) -> str:
    return "".join(text.split()).casefold()


def _get(part: JlcPart, *keys: str) -> str:
    return _attr(part, *keys, required=False)


def _fields(part: JlcPart, spec: dict[str, tuple[str, ...]]) -> dict[str, str]:
    out = {}
    for key, names in spec.items():
        v = _get(part, *names)
        if v:
            out[key] = v
    return out


def _single_diode(part: JlcPart) -> str:
    """'' when the record describes one diode, else the reason."""
    config = _get(part, "Diode Configuration")
    return "" if _fold(config) in SINGLE_CONFIG else f"diode configuration {config!r}"


DIODE_FIELDS = {"vr": ("Voltage - DC Reverse(Vr)",), "if": ("Current - Rectified",),
                "vf": ("Voltage - Forward(Vf@If)",)}


NOT_DISCRETE = ("driver", "photo", "laser", "varactor", "bridge", "module", "array", "display")


def _diode(part: JlcPart, tname: str) -> Discrete | None:
    if any(word in tname for word in NOT_DISCRETE):
        return None
    if tname.startswith("led indication") or tname.startswith("light emitting diodes"):
        color = _get(part, "Illumination Color")
        why = _single_diode(part)
        if not why and ("/" in color or "rgb" in _fold(color)):
            why = f"multi-colour LED ({color})"
        return _make("leds_optoelectronics", "LED", TWO, DIODE_CHECK, why,
                     _fields(part, {"color": ("Illumination Color",), "vf": ("Voltage - Forward(Vf)",)}))
    if "tvs" in tname or "esd" in tname:
        channels = _fold(_get(part, "Number of Channels"))
        polarity = _get(part, "Polarity")
        why = ""
        fields = _fields(part, {"vr": ("Reverse Stand-Off Voltage (Vrwm)",)})
        if channels not in ("", "1", "single-channel", "single"):
            why = f"{_get(part, 'Number of Channels')} channels"
        elif _fold(polarity) == "unidirectional":  # drawn as a zener, as KiCad's stock SMAJ*A / SM6T*A
            return _make("diodes", "D_Zener", TWO, DIODE_CHECK, "", fields)
        elif _fold(polarity) != "bidirectional":
            why = f"polarity {polarity or 'unknown'}"
        return _make("diodes", "D_TVS", TWO, "bidirectional: pad order free", why, fields)
    if "zener" in tname:
        return _make("diodes", "D_Zener", TWO, DIODE_CHECK, _single_diode(part),
                     _fields(part, {"vz": ("Zener Voltage(Nom)",)}))
    if "schottky" in tname:
        return _make("diodes", "D_Schottky", TWO, DIODE_CHECK, _single_diode(part), _fields(part, DIODE_FIELDS))
    if "diode" in tname and "bridge" not in tname:
        return _make("diodes", "D", TWO, DIODE_CHECK, _single_diode(part), _fields(part, DIODE_FIELDS))
    return None


def _make(category, symbol, pads, checklist, why, fields) -> Discrete:
    return Discrete(category, None if why else symbol, pads, fields, checklist, why)


def _transistor(part: JlcPart, tname: str) -> Discrete | None:
    number = _get(part, "Number")
    text = _fold(f"{_get(part, 'Type')} {number}")
    if "mosfet" in tname:
        pol = "N" if "n-channel" in text else "P" if "p-channel" in text else ""
        fields = {"type": f"{pol}-MOSFET"} if pol else {}
        fields |= _fields(part, {"v_max": ("Drain to Source Voltage",),
                                 "i_max": ("Current - Continuous Drain(Id)",), "rds_on": ("RDS(on)",)})
        symbol, check = f"Q_{pol}MOS_GSD", "pads 1/2/3 = G/S/D"
    elif "bjt" in tname:
        pol = "NPN" if "npn" in text else "PNP" if "pnp" in text else ""
        fields = {"type": pol} if pol else {}
        fields |= _fields(part, {"v_max": ("Collector - Emitter Voltage VCEO",),
                                 "i_max": ("Current - Collector(Ic)",)})
        symbol, check = f"Q_{pol}_BEC", "pads 1/2/3 = B/E/C"
    else:
        return None
    why = ""
    if number and not number.strip().startswith("1 "):
        why = f"{number} devices"
    elif not pol:
        why = "polarity unknown"
    elif part.package not in SOT23_FAMILY:
        why = f"package {part.package} is not SOT-23-like (pinout unknown)"
    return _make("transistors", symbol, THREE, check, why, fields)


def classify(part: JlcPart) -> Discrete | None:
    tname = part.type_name.casefold()
    return _diode(part, tname) or _transistor(part, tname)


# Plan 8: the stock KiCad footprint of a discrete's package. JLC spells one
# package in several ways per maker; canonical_package() folds them.
FOOTPRINTS: dict[str, tuple[str, str]] = {
    "SOD-123": ("Diode_SMD:D_SOD-123", "Diode_SMD"),
    "SOD-123F": ("Diode_SMD:D_SOD-123F", "Diode_SMD"),
    "SOD-323": ("Diode_SMD:D_SOD-323", "Diode_SMD"),
    "SOD-323F": ("Diode_SMD:D_SOD-323F", "Diode_SMD"),
    "SOD-523": ("Diode_SMD:D_SOD-523", "Diode_SMD"),
    "SOD-128": ("Diode_SMD:D_SOD-128", "Diode_SMD"),
    "SMA": ("Diode_SMD:D_SMA", "Diode_SMD"),
    "SMB": ("Diode_SMD:D_SMB", "Diode_SMD"),
    "SMC": ("Diode_SMD:D_SMC", "Diode_SMD"),
    "SOT-23": ("Package_TO_SOT_SMD:SOT-23", "Package_TO_SOT_SMD"),
    "SOT-323": ("Package_TO_SOT_SMD:SOT-323_SC-70", "Package_TO_SOT_SMD"),
    "SOT-363": ("Package_TO_SOT_SMD:SOT-363_SC-70-6", "Package_TO_SOT_SMD"),
    "LED-0603": ("LED_SMD:LED_0603_1608Metric", "LED_SMD"),
    "LED-0805": ("LED_SMD:LED_0805_2012Metric", "LED_SMD"),
    "LED-1206": ("LED_SMD:LED_1206_3216Metric", "LED_SMD"),
}
_SPELLINGS = {
    "SMA": ("SMA", "SMA(DO-214AC)", "DO-214AC(SMA)", "DO-214AC"),
    "SMB": ("SMB", "SMB(DO-214AA)", "DO-214AA(SMB)", "DO-214AA"),
    "SMC": ("SMC", "SMC(DO-214AB)", "DO-214AB(SMC)", "DO-214AB"),
    "SOD-123F": ("SOD-123F", "SOD-123FL"),
    "SOD-323": ("SOD-323", "SOD-323(SC-90)"),
    "SOT-23": ("SOT-23", "SOT-23-3", "SOT-23-3L", "TO-236", "TO-236AB"),
    "SOT-323": ("SOT-323", "SOT-323-3", "SC-70", "SC-70-3"),
    "SOT-363": ("SOT-363", "SC-70-6(SOT-363)", "TSSOP-6(SOT-363)", "SC-70-6"),
}
_CANONICAL = {_fold(s): key for key, spellings in _SPELLINGS.items() for s in spellings}
_CANONICAL.update({_fold(k): k for k in FOOTPRINTS if not k.startswith("LED-")})


def canonical_package(part: JlcPart) -> str | None:
    """The FOOTPRINTS key of a discrete's JLC package text, or None."""
    pkg = _fold(part.package)
    if pkg in ("0603", "0805", "1206"):
        d = classify(part)
        return f"LED-{pkg}" if d is not None and d.category == "leds_optoelectronics" else None
    return _CANONICAL.get(pkg)


def stock_footprint(part: JlcPart) -> tuple[str, str] | None:
    """(stock footprint ref, LIB family) for a discrete's package, or None."""
    key = canonical_package(part)
    return FOOTPRINTS.get(key) if key else None

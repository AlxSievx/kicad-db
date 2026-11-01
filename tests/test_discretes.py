import pytest

from fakes import rec
from libkit.discretes import classify
from libkit.entries import kind_of
from libkit.jlc import parse_record


def part(code):
    return parse_record(rec(code))


@pytest.mark.parametrize("code, symbol, category", [
    ("C81598", "D", "diodes"), ("C8678", "D_Schottky", "diodes"), ("C8056", "D_Zener", "diodes"),
    ("C78402", "D_TVS", "diodes"), ("C2286", "LED", "leds_optoelectronics"),
    ("C20917", "Q_NMOS_GSD", "transistors"), ("C15127", "Q_PMOS_GSD", "transistors"),
    ("C20526", "Q_NPN_BEC", "transistors")])
def test_classify(code, symbol, category):
    d = classify(part(code))
    assert (d.symbol, d.category) == (symbol, category)
    assert d.pads == (frozenset({"1", "2", "3"}) if category == "transistors" else frozenset({"1", "2"}))


def test_transistor_default_only_sot23():  # Review Focus 4
    d = classify(part("C2932"))
    assert d.symbol is None and d.category == "transistors" and "TO-247" in d.why
    assert d.fields["type"] == "N-MOSFET"


def test_multi_channel_tvs_no_default():
    d = classify(part("C7420375"))
    assert d.symbol is None and d.category == "diodes" and d.why


def test_dual_diode_no_default():  # BAT54S
    d = classify(part("C8592"))
    assert d.symbol is None and "Series" in d.why


def test_fields():
    assert classify(part("C20917")).fields == {"type": "N-MOSFET", "v_max": "30V", "i_max": "5.7A",
                                               "rds_on": "48mΩ@2.5V"}
    assert classify(part("C20526")).fields == {"type": "NPN", "v_max": "40V", "i_max": "200mA"}
    assert classify(part("C81598")).fields == {"vr": "75V", "if": "150mA", "vf": "1V@50mA"}
    assert classify(part("C8056")).fields == {"vz": "3.3V"}
    assert classify(part("C78402")).fields["vr"] == "5V"


def test_led_fields():
    assert classify(part("C2286")).fields == {"color": "Red", "vf": "1.8V~2.4V"}


def test_checklist():
    assert "cathode" in classify(part("C81598")).checklist
    assert classify(part("C20917")).checklist == "pads 1/2/3 = G/S/D"
    assert classify(part("C20526")).checklist == "pads 1/2/3 = B/E/C"


def test_not_discrete():
    assert classify(part("C6186")) is None
    assert kind_of(part("C81598")) is None and kind_of(part("C8056")) is None


def test_type_name_parsed():
    assert part("C8678").type_name == "Schottky Diodes"

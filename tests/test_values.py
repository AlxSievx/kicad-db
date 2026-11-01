import pytest

from libkit.values import format_value, parse_value, spellings


@pytest.mark.parametrize("text,unit,v", [
    ("100nF", "F", 1e-7), ("100n", "F", 1e-7), ("0.1uF", "F", 1e-7), ("0.1µF", "F", 1e-7),
    ("4n7", "F", 4.7e-9), ("10pF", "F", 1e-11), ("1F", "F", 1.0),
    ("4.7k", "Ω", 4700), ("4k7", "Ω", 4700), ("4.7kΩ", "Ω", 4700), ("100R", "Ω", 100),
    ("100", "Ω", 100), ("1R5", "Ω", 1.5), ("0R", "Ω", 0), ("1M", "Ω", 1e6), ("2m2", "Ω", 2.2e-3),
    ("10uH", "H", 1e-5), ("10µH", "H", 1e-5), ("4u7", "H", 4.7e-6),
])
def test_parse_value(text, unit, v):
    assert parse_value(text, unit) == pytest.approx(v)


@pytest.mark.parametrize("text,unit", [("abc", "F"), ("", "Ω"), ("10kF", "F"), ("1.2.3k", "Ω"), ("10uF", "H")])
def test_parse_value_rejects_garbage(text, unit):
    with pytest.raises(ValueError):
        parse_value(text, unit)


@pytest.mark.parametrize("v,unit,s", [
    (1e-7, "F", "100nF"), (4.7e-6, "F", "4.7uF"), (1e-11, "F", "10pF"), (2.2e-10, "F", "220pF"),
    (4700, "Ω", "4.7k"), (100, "Ω", "100R"), (0, "Ω", "0R"), (1e6, "Ω", "1M"), (1.5, "Ω", "1.5R"),
    (1e-5, "H", "10uH"),
])
def test_format_value(v, unit, s):
    assert format_value(v, unit) == s


def test_spellings():
    assert spellings(1e-7, "F") == ["100nF", "100n", "0.1uF", "0.1µF"]
    assert spellings(4.7e-6, "F") == ["4.7uF", "4.7u", "4u7", "4.7µF"]
    assert spellings(4700, "Ω") == ["4.7k", "4k7", "4.7kΩ"]
    assert spellings(100, "Ω") == ["100R", "100Ω"]
    assert spellings(1e-5, "H") == ["10uH", "10u", "10µH"]


def test_milli_ohm_names_and_values():  # plan 6 Review Focus 1
    from libkit.entries import passive_name
    assert format_value(0.01, "Ω") == "10mR"
    assert parse_value("10mR", "Ω") == parse_value("10m", "Ω") == 0.01
    assert parse_value("10M", "Ω") == 1e7 and format_value(1e7, "Ω") == "10M"
    assert passive_name("resistor", 0.01, "2512", tolerance=0.01) == "R_10mR_2512_1pct"
    assert "10mΩ" in spellings(0.01, "Ω")


def test_metric_1210_2512():
    from libkit.entries import footprint_for
    assert footprint_for("capacitor", "1210") == "LIB_Passives_SMD:C_1210_3225Metric"
    assert footprint_for("resistor", "2512") == "LIB_Passives_SMD:R_2512_6332Metric"

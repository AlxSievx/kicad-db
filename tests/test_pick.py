from dataclasses import replace

import pytest

from fakes import FIXTURES, fake_get, rec
from libkit.datasheet import Result
from libkit.jlc import JlcPart, parse_record
from libkit.jlcsearch import Candidate, capacitors, resistors
from libkit.net import NetError
from libkit.pick import Need, pick


def make_lookup(brand: str = "Samsung Electro-Mechanics", brands: dict | None = None, stock: dict | None = None,
                calls: list | None = None, types: dict | None = None):
    """A lookup that answers from tests/fixtures/jlc/ when a fixture exists,
    otherwise invents a record (given brand, generous stock, Extended unless
    `types` says otherwise)."""
    brands, stock, types = brands or {}, stock or {}, types or {}

    def lookup(lcsc):
        if calls is not None:
            calls.append(lcsc)
        if (FIXTURES / "jlc" / f"{lcsc}.json").exists():
            p = parse_record(rec(lcsc))
        else:
            p = JlcPart(lcsc, f"MPN-{lcsc}", brand, "0402", 1_000_000, "Extended",
                        f"https://www.lcsc.com/datasheet/{lcsc}.pdf", "", {})
        if lcsc in brands:
            p = replace(p, brand=brands[lcsc])
        if lcsc in stock:
            p = replace(p, stock=stock[lcsc])
        if lcsc in types:
            p = replace(p, jlc_type=types[lcsc])
        return p
    return lookup


def make_lang(langs: dict, calls: list | None = None):
    """Datasheet language per C-number ("en" when not listed)."""
    def lang(part):
        if calls is not None:
            calls.append(part.lcsc)
        return Result(langs.get(part.lcsc, "en"), "no PDF behind the link" if langs.get(part.lcsc) == "unknown" else "")
    return lang


NEED = Need("capacitor", 1e-7, "0402", 0.1, 16)
BASIC = {f"C90{i}": "Basic" for i in range(10)}


def test_pick_prefers_english_datasheet_within_tier(schema):  # rule 6
    cs = [cand("C900", stock=90_000), cand("C901", stock=50_000)]
    p = pick(NEED, cs, schema, lookup=make_lookup(types=BASIC), lang=make_lang({"C900": "zh"}))
    assert p.part.lcsc == "C901" and p.note == "" and p.datasheet.lang == "en"


def test_pick_stops_at_first_english_basic(schema):  # rule 6: no extra lookups when the first fits
    calls, checked = [], []
    cs = [cand("C900", stock=90_000), cand("C901", stock=50_000)]
    pick(NEED, cs, schema, lookup=make_lookup(types=BASIC, calls=calls), lang=make_lang({}, checked))
    assert calls == ["C900"] and checked == ["C900"]


def test_pick_basic_without_english_beats_extended_with(schema):  # rule 1 before rule 6
    calls = []
    cs = [cand("C900"), cand("C950", "Extended", stock=9_000_000)]
    p = pick(NEED, cs, schema, lookup=make_lookup(types=BASIC, calls=calls), lang=make_lang({"C900": "zh"}))
    assert p.part.lcsc == "C900" and p.note == "no English datasheet"
    assert calls == ["C900"]  # Extended candidates are not even looked up


def test_pick_unknown_language_before_chinese(schema):
    cs = [cand("C900", stock=90_000), cand("C901", stock=50_000)]
    p = pick(NEED, cs, schema, lookup=make_lookup(types=BASIC), lang=make_lang({"C900": "zh", "C901": "unknown"}))
    assert p.part.lcsc == "C901" and p.note == "datasheet language unknown (no PDF behind the link)"


def test_pick_language_checks_are_bounded(schema):
    from libkit.pick import MAX_LANG_CHECKS
    checked = []
    cs = [cand(f"C90{i}", stock=90_000 - i) for i in range(7)]
    p = pick(NEED, cs, schema, lookup=make_lookup(types=BASIC),
             lang=make_lang({c.lcsc: "zh" for c in cs}, checked))
    assert len(checked) == MAX_LANG_CHECKS and p.part.lcsc == "C900"  # best stock among equals


def test_pick_jlc_tier_counts_not_jlcsearch(schema):
    # jlcsearch calls both Basic; JLC's record says the first is Extended.
    cs = [cand("C900", stock=90_000), cand("C901", stock=50_000)]
    p = pick(NEED, cs, schema, lookup=make_lookup(types={"C900": "Extended", "C901": "Basic"}),
             lang=make_lang({"C901": "zh"}))
    assert p.part.lcsc == "C901" and p.note == "no English datasheet"


def test_pick_extended_note_combines(schema):
    p = pick(NEED, [cand("C950", "Extended")], schema, lookup=make_lookup(), lang=make_lang({"C950": "zh"}))
    assert p.note == "Extended part; no English datasheet"


@pytest.fixture
def caps():
    return capacitors("0402", 1e-7, get=fake_get("cap_0402_1e-07.json"))


@pytest.fixture
def caps10p():
    return capacitors("0402", 1e-11, get=fake_get("cap_0402_1e-11.json"))


def cand(lcsc, jlc_type="Basic", stock=50_000, tol=0.1, voltage=16, dielectric="X7R", value=1e-7):
    return Candidate(lcsc, f"MPN-{lcsc}", "0402", value, tol, voltage, None, dielectric, stock, jlc_type)


def test_candidates_parsed():
    c = resistors("0402", 10000, get=fake_get("res_0402_10000.json"))[0]
    assert (c.lcsc, c.mpn, c.package) == ("C25744", "0402WGF1002TCE", "0402")
    assert c.tolerance == 0.01 and c.power_mw == 62.5 and c.jlc_type == "Basic"
    assert c.value == 10000 and c.dielectric is None and c.stock > 0


def test_candidates_null_stock_is_unknown():
    cs = capacitors("0402", 1e-11, get=fake_get("cap_0402_1e-11.json"))
    assert any(c.stock is None for c in cs)


def test_pick_unknown_stock_asks_jlc(schema):  # Final review I1
    # jlcsearch has no stock figure for most records; JLC's own stock decides.
    cs = [cand("C900", stock=None), cand("C901", "Extended", stock=9_000_000)]
    p = pick(Need("capacitor", 1e-7, "0402", 0.1, 16), cs, schema, lookup=make_lookup())
    assert p.part.lcsc == "C900"


def test_pick_known_stock_first_within_tier(schema):  # Final review I1
    calls = []
    cs = [cand("C900", stock=None), cand("C901", stock=2_000)]
    pick(Need("capacitor", 1e-7, "0402", 0.1, 16), cs, schema, lookup=make_lookup(calls=calls))
    assert calls == ["C901"]


def test_pick_negative_tolerance_is_unknown(schema):  # Final review (rule 4)
    # tolerance_fraction -0.2 means -20%/+80% — never a "≤ 10%" part.
    p = pick(Need("capacitor", 1e-7, "0402", 0.1, 16), [cand("C900", tol=-0.2)], schema, lookup=make_lookup())
    assert p.part is None and "tolerance" in p.note


def test_need_rejects_y5v_z5u():  # spec §6.6 rule 4
    with pytest.raises(ValueError, match="Y5V"):
        Need("capacitor", 1e-7, "0402", 0.1, 16, dielectrics=("X7R", "Y5V"))
    with pytest.raises(ValueError, match="Z5U"):
        Need("capacitor", 1e-7, "0402", 0.1, 16, dielectrics=("z5u",))


def test_pick_check_rejects_and_moves_on(schema):  # Final review M1/M2
    cs = [cand("C900", stock=9_000_000), cand("C901", stock=8_000_000)]
    p = pick(Need("capacitor", 1e-7, "0402", 0.1, 16), cs, schema, lookup=make_lookup(),
             check=lambda part: "voltage 10V at JLC" if part.lcsc == "C900" else None)
    assert p.part.lcsc == "C901"
    p = pick(Need("capacitor", 1e-7, "0402", 0.1, 16), cs, schema, lookup=make_lookup(),
             check=lambda part: "voltage 10V at JLC")
    assert p.part is None and "voltage 10V at JLC" in p.note


def test_candidates_url():
    seen = []
    resistors("0402", 4700, get=lambda u: (seen.append(u), {"resistors": []})[1])
    capacitors("0603", 1e-7, get=lambda u: (seen.append(u), {"capacitors": []})[1])
    assert seen == ["https://jlcsearch.tscircuit.com/resistors/list.json?package=0402&resistance=4700",
                    "https://jlcsearch.tscircuit.com/capacitors/list.json?package=0603&capacitance=1e-07"]


def test_candidates_bad_shape_raises():
    with pytest.raises(NetError):
        resistors("0402", 10000, get=lambda u: {"oops": 1})
    with pytest.raises(NetError):
        capacitors("0402", 1e-7, get=lambda u: {"capacitors": [{"lcsc": 1}]})


def test_value_match_tolerance():  # Review Focus 2
    cs = capacitors("0402", 1e-7, get=fake_get("cap_0402_1e-07.json"))
    assert cs and all(abs(c.value - 1e-7) / 1e-7 < 0.005 for c in cs)
    assert capacitors("0402", 1e-6, get=fake_get("cap_0402_1e-07.json")) == []  # 100n never satisfies 1u
    assert resistors("0402", 47000, get=fake_get("res_0402_10000.json")) == []
    r47 = {"resistors": [{**rs, "resistance": 4700} for rs in fake_get("res_0402_10000.json")("")["resistors"][:3]]}
    assert resistors("0402", 47000, get=lambda u: r47) == []  # 4.7k is not 47k
    assert len(resistors("0402", 4700, get=lambda u: r47)) == 3


def test_pick_prefers_basic(schema, caps):
    p = pick(Need("capacitor", 1e-7, "0402", 0.1, 16), caps, schema, lookup=make_lookup())
    assert p.part.lcsc == "C1525" and p.part.jlc_type == "Basic" and p.note == ""
    assert p.candidate.lcsc == "C1525"


def test_pick_basic_before_bigger_extended_stock(schema):
    cs = [cand("C900", "Extended", stock=9_000_000), cand("C901", "Basic", stock=5_000)]
    assert pick(Need("capacitor", 1e-7, "0402", 0.1, 16), cs, schema, lookup=make_lookup()).part.lcsc == "C901"


def test_pick_preferred_counts_as_basic(schema):
    cs = [cand("C900", "Basic", stock=5_000), cand("C901", "Preferred", stock=8_000)]
    assert pick(Need("capacitor", 1e-7, "0402", 0.1, 16), cs, schema, lookup=make_lookup()).part.lcsc == "C901"


def test_pick_respects_min_voltage(schema, caps):
    p = pick(Need("capacitor", 1e-7, "0402", 0.1, 50), caps, schema, lookup=make_lookup())
    assert p.part is not None and p.candidate.voltage >= 50


def test_pick_respects_tolerance(schema):
    cs = [cand("C900", tol=0.2, stock=9_000_000), cand("C901", tol=0.1), cand("C902", tol=None, stock=8_000_000)]
    assert pick(Need("capacitor", 1e-7, "0402", 0.1, 16), cs, schema, lookup=make_lookup()).part.lcsc == "C901"
    p = pick(Need("capacitor", 1e-7, "0402", 0.05, 16), cs, schema, lookup=make_lookup())
    assert p.part is None and "tolerance" in p.note


def test_pick_rejects_y5v(schema, caps):
    bad = [replace(c, dielectric="Y5V" if i % 2 else "Z5U") for i, c in enumerate(caps)]
    p = pick(Need("capacitor", 1e-7, "0402", 0.2, 16), bad, schema, lookup=make_lookup())
    assert p.part is None and "dielectric" in p.note and "C0G/NP0/X7R/X5R" in p.note


def test_pick_c0g_by_default(schema, caps10p):
    p = pick(Need("capacitor", 1e-11, "0402", 0.05, 50), caps10p, schema, lookup=make_lookup())
    assert p.part.lcsc == "C32949"


def test_pick_skips_unknown_brand(schema):
    cs = [cand("C900", stock=9_000_000), cand("C901", stock=8_000_000)]
    lk = make_lookup(brands={"C900": "NoName"})
    assert pick(Need("capacitor", 1e-7, "0402", 0.1, 16), cs, schema, lookup=lk).part.lcsc == "C901"


def test_pick_unknown_brands_note_and_limit(schema):
    calls = []
    cs = [cand(f"C9{i:02}", stock=9_000_000 - i) for i in range(12)]
    p = pick(Need("capacitor", 1e-7, "0402", 0.1, 16), cs, schema, lookup=make_lookup("NoName", calls=calls))
    assert p.part is None and p.note == "no known manufacturer among 8 checked"
    assert len(calls) == 8


def test_pick_rechecks_stock_at_jlc(schema):
    cs = [cand("C900", stock=9_000_000), cand("C901", stock=8_000_000)]
    lk = make_lookup(stock={"C900": 10})
    assert pick(Need("capacitor", 1e-7, "0402", 0.1, 16), cs, schema, lookup=lk).part.lcsc == "C901"


def test_pick_lookup_none_skipped(schema):
    cs = [cand("C900", stock=9_000_000), cand("C901", stock=8_000_000)]
    inner = make_lookup()
    p = pick(Need("capacitor", 1e-7, "0402", 0.1, 16), cs, schema,
             lookup=lambda c: None if c == "C900" else inner(c))
    assert p.part.lcsc == "C901"


def test_pick_extended_noted(schema):
    cs = [cand("C900", "Extended"), cand("C901", "Extended")]
    p = pick(Need("capacitor", 1e-7, "0402", 0.1, 16), cs, schema, lookup=make_lookup())
    assert p.part.lcsc == "C900" and p.note == "Extended part"


def test_pick_stock_threshold(schema):
    cs = [cand("C900", stock=999), cand("C901", stock=10)]
    p = pick(Need("capacitor", 1e-7, "0402", 0.1, 16), cs, schema, lookup=make_lookup())
    assert p.part is None and "stock" in p.note


def test_pick_no_candidates(schema):
    p = pick(Need("resistor", 1e3, "0402", 0.01), [], schema, lookup=make_lookup())
    assert p.part is None and p.candidate is None and p.note


def test_pick_resistor_ignores_dielectric(schema):
    cs = resistors("0402", 10000, get=fake_get("res_0402_10000.json"))
    p = pick(Need("resistor", 10000, "0402", 0.01), cs, schema, lookup=make_lookup("YAGEO"))
    assert p.part.lcsc == "C25744" and p.note == ""


def test_pick_lookup_error_propagates(schema, caps):
    def boom(c):
        raise NetError(f"{c}: HTTP 500")
    with pytest.raises(NetError):
        pick(Need("capacitor", 1e-7, "0402", 0.1, 16), caps, schema, lookup=boom)


def test_min_power_filters_candidates(schema):  # plan 6 task 2
    def cand(lcsc, mw):
        return Candidate(lcsc, f"M{lcsc}", "2512", 0.01, 0.01, None, mw, None, 50_000, "Basic")
    need = Need("resistor", 0.01, "2512", 0.01, min_power=1.0)
    p = pick(need, [cand("C901", 500), cand("C902", 1000)], schema, lookup=make_lookup(brand="Yageo"))
    assert p.part.lcsc == "C902"
    p = pick(need, [cand("C901", 500)], schema, lookup=make_lookup(brand="Yageo"))
    assert p.part is None and "power ≥ 1W" in p.note


def test_jlcsearch_power_units():  # jlcsearch's power_watts is mW for chips, W for 1W+ parts
    from libkit.jlcsearch import _candidate
    base = {"lcsc": 1, "mfr": "X", "package": "2512", "resistance": 0.01, "stock": 10, "tolerance_fraction": 0.01}
    assert _candidate({**base, "power_watts": 62.5}, "resistance", "resistors").power_mw == 62.5
    assert _candidate({**base, "power_watts": 750}, "resistance", "resistors").power_mw == 750
    assert _candidate({**base, "power_watts": 3}, "resistance", "resistors").power_mw == 3000
    assert _candidate({**base, "power_watts": 1}, "resistance", "resistors").power_mw == 1000

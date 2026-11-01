import dataclasses

import pytest
from conftest import part

from libkit.text import build_description, build_keywords


@pytest.fixture
def cap_part(minilib):
    return part(minilib, "C_100n_0402_16V_X7R")


def with_data(p, **kw):
    return dataclasses.replace(p, data={**p.data, **kw})


def test_description_from_template(cap_part, schema):
    assert build_description(cap_part, schema) == "100nF 16V X7R ±10% 0402 capacitor"


def test_description_template_skips_empty_fields(minilib, schema):
    r = with_data(part(minilib, "R_10k_0402_1pct"), power="")
    assert build_description(r, schema) == "10k ±1% 0402 resistor"


def test_explicit_description_wins(cap_part, schema):
    assert build_description(with_data(cap_part, description="Special cap"), schema) == "Special cap"


def test_deprecated_description_prefixed(cap_part, schema):
    dep = with_data(cap_part, status="deprecated")
    assert build_description(dep, schema) == "DEPRECATED 100nF 16V X7R ±10% 0402 capacitor"


def test_keywords(cap_part, schema):
    assert build_keywords(cap_part, schema) == (
        "100nF 100n 0.1uF 0.1µF 0402 Samsung CL05B104KO5NNNC C1525 16V X7R ±10%"
    )


def test_keywords_dedupe_and_no_unit_category(cap_part, schema):
    ic = dataclasses.replace(cap_part, category="ics_power",
                             data={**cap_part.data, "value": "CL05B104KO5NNNC"})
    assert build_keywords(ic, schema) == "CL05B104KO5NNNC 0402 Samsung C1525"


def test_keywords_unparseable_value_kept_raw(cap_part, schema):
    assert build_keywords(with_data(cap_part, value="DNP"), schema).startswith("DNP 0402 ")


def test_deprecated_has_no_keywords(cap_part, schema):
    assert build_keywords(with_data(cap_part, status="deprecated"), schema) == ""

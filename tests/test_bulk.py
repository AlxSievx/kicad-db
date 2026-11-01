import json
import urllib.parse

import pytest

from conftest import errors
from fakes import FIXTURES, load
from libkit import __main__ as cli, net
from libkit.bulk import apply, plan
from libkit.net import NetError
from libkit.parts import load_parts
from libkit.schema import load_schema

DIELECTRICS = ("C0G", "NP0", "X7R", "X5R")
SEARCH_FIXTURES = {
    ("resistors", "10000"): "res_0402_10000.json",
    ("capacitors", "1e-07"): "cap_0402_1e-07.json",
    ("capacitors", "1e-11"): "cap_0402_1e-11.json",
}


def fake_get(calls=None):
    """jlcsearch stand-in: recorded responses for 0402 10k / 100n / 10p, empty lists otherwise."""
    def get(url):
        if calls is not None:
            calls.append(url)
        u = urllib.parse.urlparse(url)
        kind = u.path.split("/")[1]
        q = dict(urllib.parse.parse_qsl(u.query))
        fname = SEARCH_FIXTURES.get((kind, q.get("resistance") or q.get("capacitance")))
        return load(f"jlcsearch/{fname}") if fname and q["package"] == "0402" else {kind: []}
    return get


def jlc_response(code):
    """JLC search response for one code: recorded when a fixture exists, else 'not listed'."""
    f = FIXTURES / "jlc" / f"{code}.json"
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    return {"code": 200, "data": {"componentPageInfo": {"list": []}}}


def fake_lookup(calls=None, fail_on=None, attrs=None):
    from dataclasses import replace
    from libkit.jlc import lookup

    def lk(code):
        if calls is not None:
            calls.append(code)
            if fail_on is not None and len(calls) == fail_on:
                raise NetError(f"{code}: HTTP 500")
        part = lookup(code, post=lambda u, b: jlc_response(b["keyword"]))
        if part is not None and attrs:
            a = {**part.attributes, **attrs}
            part = replace(part, attributes={k: v for k, v in a.items() if v is not None})
        return part
    return lk


def add_part(root, category, entry):
    f = root / "parts" / f"{category}.yaml"
    lines = [f"  - name: {entry.pop('name')}"] + [f"    {k}: \"{v}\"" for k, v in entry.items()]
    f.write_text(f.read_text(encoding="utf-8") + "\n".join(lines) + "\n", encoding="utf-8")


def cap10p(name="C_10p_0402_50V_NP0", lcsc="C1545", status="active", dielectric="NP0"):
    return {"name": name, "symbol": "C", "footprint": "LIB_Passives_SMD:C_0402_1005Metric", "value": "10pF",
            "package": "0402", "manufacturer": "FH", "mpn": "0402CG100J500NT", "lcsc": lcsc, "jlc_type": "Extended",
            "datasheet": f"https://www.lcsc.com/datasheet/{lcsc}.pdf", "status": status, "voltage": "50V",
            "dielectric": dielectric, "tolerance": "±5%"}


def plan10p(root, **kw):
    return plan(root, "capacitor", "E6", 1e-11, 1e-11, "0402", 0.05, 50, DIELECTRICS,
                get=fake_get(), lookup=fake_lookup(), **kw)


def test_bulk_plan_rows(minilib):
    calls = []
    rows = plan(minilib, "capacitor", "E6", 1e-7, 1e-7, "0402", 0.1, 16, ("X7R", "X5R"),
                get=fake_get(calls), lookup=fake_lookup())
    assert [r.status for r in rows] == ["exists"]  # fixture already has C_100n_0402_16V_X7R
    assert rows[0].name == "C_100n_0402_16V_X7R" and rows[0].value == "100nF"
    assert calls == []  # an existing part that fits needs no network


def test_bulk_existing_must_fit_the_need(minilib):
    # The library's 100n is 16V; a 50V request is not satisfied by it.
    rows = plan(minilib, "capacitor", "E6", 1e-7, 1e-7, "0402", 0.1, 50, DIELECTRICS,
                get=fake_get(), lookup=fake_lookup())
    assert rows[0].status != "exists"


def test_bulk_new_row(minilib):
    [row] = plan10p(minilib)
    assert row.status == "new" and row.name == "C_10p_0402_50V_C0G" and row.note == ""
    assert row.entry["lcsc"] == "C32949" and row.entry["manufacturer"] == "Samsung"


def test_bulk_skips_existing(minilib):  # Review Focus 3
    # C32949 is already in the library under another (retired) name.
    add_part(minilib, "capacitors", cap10p(name="C_10p_0402_50V_C0G_old", lcsc="C32949", status="deprecated"))
    [row] = plan10p(minilib)
    assert row.status == "exists" and "C_10p_0402_50V_C0G_old" in row.note and "C32949" in row.note


def test_bulk_skips_existing_name(minilib):  # Review Focus 3
    # The pick's name exists (deprecated, other LCSC): names are never reused.
    add_part(minilib, "capacitors", cap10p(name="C_10p_0402_50V_C0G", lcsc="C1545", status="deprecated",
                                           dielectric="C0G"))
    [row] = plan10p(minilib)
    assert row.status == "exists" and row.name == "C_10p_0402_50V_C0G"


def test_bulk_existing_value_fits(minilib):
    # An active 10p NP0 50V part already covers the need; no second 10p is added.
    add_part(minilib, "capacitors", cap10p())
    [row] = plan10p(minilib)
    assert row.status == "exists" and row.name == "C_10p_0402_50V_NP0"


def test_bulk_jlc_record_must_match_request(minilib):  # Final review M2
    # jlcsearch said 50V, JLC's own record says 16V: not a 50V part.
    [row] = plan(minilib, "capacitor", "E6", 1e-11, 1e-11, "0402", 0.05, 50, DIELECTRICS,
                 get=fake_get(), lookup=fake_lookup(attrs={"Voltage Rating": "16V"}))
    assert row.status == "none" and "16V" in row.note


def test_bulk_incomplete_record_skipped(minilib):  # Final review M1
    [row] = plan(minilib, "capacitor", "E6", 1e-11, 1e-11, "0402", 0.05, 50, DIELECTRICS,
                 get=fake_get(), lookup=fake_lookup(attrs={"Tolerance": None}))
    assert row.status == "none" and "Tolerance" in row.note


def test_cli_rejects_y5v(offline, capsys):  # spec §6.6 rule 4
    assert cli.main(CLI_10P + ["--dielectric", "Y5V"]) == 1
    assert "Y5V" in capsys.readouterr().err


def test_bulk_none_reported(minilib):
    rows = plan(minilib, "resistor", "E12", 1000, 1200, "0402", 0.01, None, (),
                get=fake_get(), lookup=fake_lookup())
    assert [(r.value, r.status) for r in rows] == [("1k", "none"), ("1.2k", "none")]
    assert all(r.note and r.entry is None for r in rows)


def test_bulk_apply_writes_and_builds(minilib):
    rows = plan10p(minilib)
    assert apply(minilib, "capacitor", rows) == 1
    schema = load_schema(minilib)
    assert "C_10p_0402_50V_C0G" in {p.name for p in load_parts(minilib, schema)}
    assert errors(minilib) == []
    assert "C_10p_0402_50V_C0G" in (minilib / "symbols" / "LIB_Capacitors.kicad_sym").read_text(encoding="utf-8")


def test_bulk_apply_nothing_new(minilib):
    before = (minilib / "parts" / "capacitors.yaml").read_bytes()
    rows = plan(minilib, "capacitor", "E6", 1e-7, 1e-7, "0402", 0.1, 16, DIELECTRICS,
                get=fake_get(), lookup=fake_lookup())
    assert apply(minilib, "capacitor", rows) == 0
    assert (minilib / "parts" / "capacitors.yaml").read_bytes() == before


def test_bulk_aborts_without_writing(minilib):  # Review Focus 4
    before = (minilib / "parts" / "capacitors.yaml").read_bytes()
    with pytest.raises(NetError):
        plan(minilib, "capacitor", "E6", 1e-11, 1e-11, "0402", 0.05, 50, DIELECTRICS,
             get=fake_get(), lookup=fake_lookup(calls=[], fail_on=1))
    assert (minilib / "parts" / "capacitors.yaml").read_bytes() == before


@pytest.fixture
def offline(minilib, monkeypatch):
    monkeypatch.chdir(minilib)
    monkeypatch.setattr(net, "get_json", fake_get())
    monkeypatch.setattr(net, "post_json", lambda u, b: jlc_response(b["keyword"]))
    return minilib


CLI_10P = ["bulk-add", "capacitor", "--series", "E6", "--from", "10p", "--to", "10p", "--package", "0402",
           "--tolerance", "5%", "--voltage", "50V"]


def test_cli_dry_run_writes_nothing(offline, capsys):
    before = (offline / "parts" / "capacitors.yaml").read_bytes()
    assert cli.main(CLI_10P) == 0
    out = capsys.readouterr().out
    assert "C_10p_0402_50V_C0G" in out and "C32949" in out and "CL05C100JB5NNNC" in out and "Samsung" in out
    assert "dry run: 1 new, 0 existing, 0 without a part — rerun with --write to add" in out
    assert (offline / "parts" / "capacitors.yaml").read_bytes() == before


def test_cli_write(offline, capsys):
    assert cli.main(CLI_10P + ["--write"]) == 0
    assert "added 1" in capsys.readouterr().out
    assert "C_10p_0402_50V_C0G" in (offline / "parts" / "capacitors.yaml").read_text(encoding="utf-8")
    assert errors(offline) == []


def test_cli_resistor_series(offline, capsys):
    assert cli.main(["bulk-add", "resistor", "--series", "E12", "--from", "1k", "--to", "10k",
                     "--package", "0402", "--tolerance", "1%"]) == 0
    out = capsys.readouterr().out
    assert "dry run: 0 new, 1 existing, 12 without a part" in out


def test_cli_network_error_writes_nothing(offline, monkeypatch, capsys):
    before = (offline / "parts" / "capacitors.yaml").read_bytes()

    def boom(u, b):
        raise NetError(f"{b['keyword']}: HTTP 500")
    monkeypatch.setattr(net, "post_json", boom)
    assert cli.main(CLI_10P + ["--write"]) == 1
    err = capsys.readouterr().err
    assert "HTTP 500" in err and "C32949" in err
    assert (offline / "parts" / "capacitors.yaml").read_bytes() == before


def test_cli_bad_tolerance(offline, capsys):
    assert cli.main(CLI_10P[:-4] + ["--tolerance", "lots", "--voltage", "50V"]) == 1
    assert "tolerance" in capsys.readouterr().err

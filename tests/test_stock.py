from dataclasses import replace
from datetime import date

import pytest

from conftest import errors, part
from fakes import fake_post, rec
from libkit import __main__ as cli, net
from libkit.jlc import parse_record
from libkit.net import NetError
from libkit.stock import Change, refresh

DAY = date(2026, 11, 2)


def recorded(code):
    return parse_record(rec(code))


def fake(overrides: dict | None = None, calls: list | None = None, fail_on: int | None = None):
    """Lookup answering from the recorded fixtures; overrides map a code to a JlcPart, None, or a dict of changes."""
    overrides = overrides or {}

    def lookup(code):
        if calls is not None:
            calls.append(code)
            if fail_on is not None and len(calls) == fail_on:
                raise NetError(f"{code}: HTTP 500")
        o = overrides.get(code, {})
        if o is None:
            return None
        base = recorded(code) if code in ("C1525", "C25744", "C32949") else None
        return replace(base, **o) if base else o
    return lookup


def add_ic(root, stock_lcsc="C2071443"):
    (root / "parts" / "ics_power.yaml").write_text(
        "parts:\n"
        "  - name: TPS62130RGTR\n"
        "    symbol: R\n"
        "    footprint: LIB_Passives_SMD:R_0402_1005Metric\n"
        "    value: TPS62130RGTR\n"
        "    package: VQFN-16\n"
        "    description: buck converter\n"
        "    manufacturer: Texas Instruments\n"
        "    mpn: TPS62130RGTR\n"
        f"    lcsc: {stock_lcsc}\n"
        "    jlc_type: Extended\n"
        f"    datasheet: https://www.lcsc.com/datasheet/{stock_lcsc}.pdf\n"
        "    status: active\n", encoding="utf-8")


def ic_record(stock):
    return replace(recorded("C25744"), lcsc="C2071443", mpn="TPS62130RGTR", brand="Texas Instruments",
                   stock=stock, jlc_type="Extended")


def test_refresh_updates_stock_and_date(minilib):
    refresh(minilib, lookup=fake(), today=DAY)
    c = part(minilib, "C_100n_0402_16V_X7R").data
    assert c["stock"] == str(recorded("C1525").stock) and c["stock_checked"] == "2026-11-02"
    r = part(minilib, "R_10k_0402_1pct").data
    assert r["stock"] == str(recorded("C25744").stock) and r["stock_checked"] == "2026-11-02"
    assert errors(minilib) == []


def test_refresh_keeps_everything_else(minilib):
    before = {n: dict(part(minilib, n).data) for n in ("C_100n_0402_16V_X7R", "R_10k_0402_1pct")}
    refresh(minilib, lookup=fake(), today=DAY)
    for n, d in before.items():
        after = part(minilib, n).data
        assert {k: v for k, v in after.items() if k not in ("stock", "stock_checked")} == \
               {k: v for k, v in d.items() if k not in ("stock", "stock_checked")}


def test_refresh_reports(minilib):
    assert refresh(minilib, lookup=fake({"C1525": None}), today=DAY) == [
        Change("C_100n_0402_16V_X7R", "not_found", "C1525 is no longer listed at JLC")]
    changes = refresh(minilib, lookup=fake({"C1525": {"stock": 0}, "C25744": {"jlc_type": "Extended"}}), today=DAY)
    kinds = {(c.part, c.kind) for c in changes}
    assert ("C_100n_0402_16V_X7R", "out_of_stock") in kinds
    assert ("R_10k_0402_1pct", "type_changed") in kinds
    assert part(minilib, "R_10k_0402_1pct").data["jlc_type"] == "Extended"
    d = next(c.detail for c in changes if c.kind == "type_changed")
    assert "Basic" in d and "Extended" in d


def test_refresh_not_found_leaves_part_alone(minilib):
    before = dict(part(minilib, "C_100n_0402_16V_X7R").data)
    refresh(minilib, lookup=fake({"C1525": None}), today=DAY)
    assert part(minilib, "C_100n_0402_16V_X7R").data == before


def test_refresh_mpn_changed(minilib):
    changes = refresh(minilib, lookup=fake({"C25744": {"mpn": "0402WGF1002TCX"}}), today=DAY)
    assert [(c.part, c.kind) for c in changes] == [("R_10k_0402_1pct", "mpn_changed")]
    assert part(minilib, "R_10k_0402_1pct").data["mpn"] == "0402WGF1002TCE"  # reported, not rewritten


def test_refresh_low_stock_thresholds(minilib):
    add_ic(minilib)
    lk = fake({"C25744": {"stock": 500}, "C2071443": ic_record(500)})
    changes = refresh(minilib, lookup=lk, today=DAY)
    assert [(c.part, c.kind) for c in changes] == [("R_10k_0402_1pct", "low_stock")]
    lk = fake({"C2071443": ic_record(99)})
    assert ("TPS62130RGTR", "low_stock") in {(c.part, c.kind) for c in refresh(minilib, lookup=lk, today=DAY)}


def test_refresh_aborts_without_writing(minilib):  # Review Focus 4
    files = sorted((minilib / "parts").glob("*.yaml"))
    before = [f.read_bytes() for f in files]
    with pytest.raises(NetError):
        refresh(minilib, lookup=fake(calls=[], fail_on=2), today=DAY)
    assert [f.read_bytes() for f in files] == before


def test_refresh_unchanged_file_not_rewritten(minilib):
    add_ic(minilib)
    f = minilib / "parts" / "ics_power.yaml"
    before = f.read_bytes()
    refresh(minilib, lookup=fake({"C2071443": None}), today=DAY)
    assert f.read_bytes() == before


@pytest.fixture
def offline(minilib, monkeypatch):
    monkeypatch.chdir(minilib)
    return minilib


def test_cli_refresh(offline, monkeypatch, capsys):
    monkeypatch.setattr(net, "post_json", lambda u, b: fake_post(f"{b['keyword']}.json")(u, b))
    assert cli.main(["refresh-stock"]) == 0
    out = capsys.readouterr().out
    assert "refreshed 2 parts" in out
    assert part(offline, "R_10k_0402_1pct").data["stock_checked"] == date.today().isoformat()


def test_cli_refresh_builds_on_type_change(offline, monkeypatch, capsys):
    import json
    from fakes import load

    def post(u, b):
        data = load(f"jlc/{b['keyword']}.json")
        for r in data["data"]["componentPageInfo"]["list"]:
            if r["componentCode"] == "C25744":
                r["componentLibraryType"] = "expand"
        return data
    monkeypatch.setattr(net, "post_json", post)
    assert cli.main(["refresh-stock"]) == 0
    out = capsys.readouterr().out
    assert "type_changed" in out and "built" in out
    sym = (offline / "symbols" / "LIB_Resistors.kicad_sym").read_text(encoding="utf-8")
    assert '"JLC_Type" "Extended"' in sym


def test_cli_refresh_network_error(offline, monkeypatch, capsys):
    def boom(u, b):
        raise NetError(f"{b['keyword']}: timed out")
    monkeypatch.setattr(net, "post_json", boom)
    assert cli.main(["refresh-stock"]) == 1
    assert "timed out" in capsys.readouterr().err

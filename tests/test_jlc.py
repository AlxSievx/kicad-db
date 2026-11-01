import os

import pytest

from fakes import fake_get_bytes, fake_post, rec
from libkit.jlc import lookup, parse_record
from libkit.net import NetError


def test_parse_record_basic():
    p = parse_record(rec("C25744"))
    assert p.lcsc == "C25744"
    assert p.mpn == "0402WGF1002TCE"
    assert p.brand == "UNI-ROYAL(Uniroyal Elec)"
    assert p.package == "0402"
    assert p.jlc_type == "Basic"
    assert p.datasheet.startswith("https://www.lcsc.com/datasheet/")
    assert p.attributes["Resistance"] == "10kΩ"
    assert p.stock > 0


def test_parse_record_preferred_and_extended():
    r = rec("C25744")
    assert parse_record({**r, "preferredComponentFlag": True}).jlc_type == "Preferred"
    assert parse_record({**r, "componentLibraryType": "expand"}).jlc_type == "Extended"


def test_parse_record_missing_field_raises():
    r = dict(rec("C25744"))
    del r["stockCount"]
    with pytest.raises(NetError, match="C25744"):
        parse_record(r)


def test_lookup_exact_match_only():
    # The C1525 response also lists UC1525… parts; only the exact code counts.
    assert lookup("C1525", post=fake_post("C1525.json")).mpn == "CL05B104KO5NNNC"


def test_lookup_not_found():
    assert lookup("C999999999", post=fake_post("notfound.json")) is None


def test_lookup_bad_shape_raises():
    with pytest.raises(NetError):
        lookup("C1", post=lambda u, b: {"code": 200})


@pytest.mark.parametrize("brand,name", [
    ("Samsung Electro-Mechanics", "Samsung"),
    ("UNI-ROYAL(Uniroyal Elec)", "UNI-ROYAL"),
    ("FH(Guangdong Fenghua Advanced Tech)", "FH"),
    ("YAGEO", "Yageo"),
    ("TAIYO YUDEN", "Taiyo Yuden"),
    ("Murata Electronics", "Murata"),
])
def test_brand_canonical(schema, brand, name):  # Review Focus 1
    assert schema.canonical_manufacturer(brand) == name


def test_brand_unknown(schema):
    assert schema.canonical_manufacturer("Fenghuaxyz Ltd") is None
    assert schema.canonical_manufacturer("FHX") is None
    assert schema.canonical_manufacturer("") is None


def test_validate_still_warns_unknown_passive_manufacturer():
    from conftest import validate_one
    assert [i.severity for i in validate_one({"manufacturer": "NoName"})] == ["warning"]
    assert validate_one({"manufacturer": "Samsung"}) == []


def test_cli_jlc_prints_record(minilib, monkeypatch, capsys):
    from libkit import __main__ as cli, net
    monkeypatch.chdir(minilib)
    monkeypatch.setattr(net, "post_json", fake_post("C1525.json"))
    monkeypatch.setattr(net, "get_bytes", fake_get_bytes())
    assert cli.main(["jlc", "C1525"]) == 0
    out = capsys.readouterr().out
    assert "jlc_type: Basic" in out
    assert "canonical manufacturer: Samsung" in out
    assert "datasheet language: en" in out


def test_cli_jlc_datasheet_unreachable(minilib, monkeypatch, capsys):
    from libkit import __main__ as cli, net
    monkeypatch.chdir(minilib)
    monkeypatch.setattr(net, "post_json", fake_post("C1525.json"))
    assert cli.main(["jlc", "C1525"]) == 0  # the datasheet check never fails the lookup
    assert "datasheet language: unknown (download failed" in capsys.readouterr().out


def test_cli_jlc_not_found(monkeypatch, capsys):
    from libkit import __main__ as cli, net
    monkeypatch.setattr(net, "post_json", fake_post("notfound.json"))
    assert cli.main(["jlc", "C999999999"]) == 1
    assert "C999999999" in capsys.readouterr().err


@pytest.mark.parametrize("exc", ["http500", "incomplete"])
def test_lookup_error_names_the_part(monkeypatch, exc):  # Final review I2 / Review Focus 4
    import http.client
    import urllib.error
    from libkit import net

    def urlopen(req, timeout):
        if exc == "http500":
            raise urllib.error.HTTPError(req.full_url, 500, "boom", {}, None)
        raise http.client.IncompleteRead(b"")
    monkeypatch.setattr(net.urllib.request, "urlopen", urlopen)
    with pytest.raises(NetError, match="C1525"):
        lookup("C1525")


@pytest.mark.skipif(os.environ.get("LIBKIT_LIVE") != "1", reason="live network test")
def test_live_lookup():
    assert lookup("C1525").brand.startswith("Samsung")


def test_cli_output_survives_non_utf8_pipe(tmp_path):
    # Piped output on Windows defaults to cp1252, which has no Ω or ℃.
    import subprocess
    import sys
    from conftest import REPO
    script = tmp_path / "run.py"
    script.write_text(
        "import sys\n"
        f"sys.path[:0] = [{str(REPO / 'tests')!r}, {str(REPO / 'tools')!r}]\n"
        "from fakes import fake_post\n"
        "from libkit import __main__ as cli, net\n"
        "net.post_json = fake_post('C25744.json')\n"
        "def offline(url, **kw):\n"
        "    raise net.NetError('offline')\n"
        "net.get_bytes = offline\n"  # transient: nothing is cached in the repo
        "sys.exit(cli.main(['jlc', 'C25744']))\n", encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONIOENCODING", "PYTHONUTF8")}
    env["PYTHONIOENCODING"] = "cp1252"
    r = subprocess.run([sys.executable, str(script)], capture_output=True, cwd=REPO, env=env)
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")
    assert "10kΩ" in r.stdout.decode("utf-8")

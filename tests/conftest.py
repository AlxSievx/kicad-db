import shutil
from pathlib import Path

import pytest

from libkit.parts import Part, load_parts, validate
from libkit.schema import load_schema

REPO = Path(__file__).resolve().parents[1]
FIXTURE = Path(__file__).parent / "fixtures" / "minilib"


@pytest.fixture(autouse=True)
def _offline_by_default(monkeypatch):
    """No real network in tests (live tests opt in with LIBKIT_LIVE=1), and no
    retry pauses. Tests that exercise net.py replace urlopen themselves."""
    import os
    import urllib.error
    from libkit import net
    monkeypatch.setattr(net, "BACKOFF", (0.0,))
    monkeypatch.setattr(net, "MIN_INTERVAL", 0.0)  # test_rate_limit sets its own
    if os.environ.get("LIBKIT_LIVE") != "1":
        def blocked(req, timeout=None):
            raise urllib.error.URLError("network disabled in tests")
        monkeypatch.setattr(net.urllib.request, "urlopen", blocked)


@pytest.fixture
def minilib(tmp_path) -> Path:
    """A throwaway library root: fixture parts + the real schema."""
    root = tmp_path / "lib"
    shutil.copytree(FIXTURE, root)
    shutil.copytree(REPO / "schema", root / "schema")
    return root


@pytest.fixture
def schema(minilib):
    return load_schema(minilib)


def part(root: Path, name: str) -> Part:
    parts = load_parts(root, load_schema(root))
    return next(p for p in parts if p.name == name)


def errors(root: Path):
    s = load_schema(root)
    return [i for i in validate(load_parts(root, s), s, root) if i.severity == "error"]


VALID_CAP = {
    "name": "C_1u_0402_10V_X5R",
    "symbol": "C",
    "footprint": "LIB_Passives_SMD:C_0402_1005Metric",
    "value": "1uF",
    "package": "0402",
    "manufacturer": "Samsung",
    "mpn": "CL05A105KP5NNNC",
    "lcsc": "C52923",
    "jlc_type": "Basic",
    "datasheet": "https://www.lcsc.com/datasheet/C52923.pdf",
    "status": "active",
    "voltage": "10V",
    "dielectric": "X5R",
    "tolerance": "±10%",
}


def validate_one(overrides: dict, category: str = "capacitors", base: dict | None = None):
    """Validate one part built from VALID_CAP; a None override deletes the key."""
    data = dict(VALID_CAP if base is None else base)
    for k, v in overrides.items():
        if v is None:
            data.pop(k, None)
        else:
            data[k] = v
    s = load_schema(REPO)
    p = Part(name=data.get("name", ""), category=category, data=data, source=Path("x.yaml"))
    return validate([p], s)


def only_error(issues) -> str:
    errs = [i for i in issues if i.severity == "error"]
    assert len(errs) == 1, issues
    return errs[0].message

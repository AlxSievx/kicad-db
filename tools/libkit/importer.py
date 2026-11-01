"""Fetch a part's symbol, footprint and 3D model from EasyEDA (easyeda2kicad).

easyeda2kicad runs as a separate process (it is AGPL-3.0; libkit only calls
it) and writes KiCad 6-era files; `kicad-cli … upgrade` brings them to the
KiCad 10 format before anything parses them.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from . import kicad
from .net import NetError
from .sexpr import find, find_all, parse

TIMEOUT = 120


@dataclass
class Fetched:
    symbol: list | None
    footprint: list | None
    footprint_name: str | None
    step: Path | None


def fetch_easyeda(lcsc: str, workdir: Path, run=subprocess.run, upgrade=None) -> Fetched:
    upgrade = upgrade or kicad.upgrade
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    out = workdir / "E2K"
    cmd = [sys.executable, "-m", "easyeda2kicad", "--full", "--lcsc_id", lcsc, "--output", str(out)]
    try:
        r = run(cmd, cwd=workdir, capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=TIMEOUT)
    except subprocess.TimeoutExpired as e:
        raise NetError(f"{lcsc}: easyeda2kicad timed out after {TIMEOUT} s") from e
    sym_file, fp_dir = workdir / "E2K.kicad_sym", workdir / "E2K.pretty"
    fp_files = sorted(fp_dir.glob("*.kicad_mod")) if fp_dir.exists() else []
    if not sym_file.exists() and not fp_files:
        tail = (r.stderr or r.stdout or "").strip()[-300:]
        raise NetError(f"{lcsc}: easyeda2kicad produced no files: {tail}")

    symbol = footprint = name = step = None
    up = workdir / "up"
    if sym_file.exists():
        upgrade("sym", sym_file, up / "E2K.kicad_sym")
        syms = find_all(parse((up / "E2K.kicad_sym").read_text(encoding="utf-8")), "symbol")
        symbol = syms[0] if syms else None
    if fp_files:
        upgrade("fp", fp_dir, up / "E2K.pretty")
        up_files = sorted((up / "E2K.pretty").glob("*.kicad_mod"))
        if up_files:
            footprint = parse(up_files[0].read_text(encoding="utf-8"))
            name = str(footprint[1])
            model = find(footprint, "model")
            steps = sorted((workdir / "E2K.3dshapes").glob("*.step"))
            if model is not None:
                wanted = workdir / "E2K.3dshapes" / (Path(str(model[1])).stem + ".step")
                step = wanted if wanted.exists() else None
            if step is None and len(steps) == 1:
                step = steps[0]
    return Fetched(symbol, footprint, name, step)

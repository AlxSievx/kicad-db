"""Locating the KiCad installation."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

DEFAULT_CLI = Path(r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe")
DEFAULT_SHARE = Path(r"C:\Program Files\KiCad\10.0\share\kicad")


def find_kicad_cli() -> Path | None:
    env = os.environ.get("KICAD_CLI")
    if env and Path(env).exists():
        return Path(env)
    found = shutil.which("kicad-cli")
    if found:
        return Path(found)
    return DEFAULT_CLI if DEFAULT_CLI.exists() else None


def kicad_share() -> Path:
    return Path(os.environ.get("KICAD_SHARE", DEFAULT_SHARE))


def upgrade(kind: str, src: Path, dst: Path, run=subprocess.run) -> None:
    """Convert a symbol library ("sym") or footprint folder ("fp") to the
    current KiCad format with `kicad-cli <kind> upgrade`."""
    if kind not in ("sym", "fp"):
        raise ValueError(f"upgrade kind must be sym or fp, not {kind!r}")
    cli = find_kicad_cli()
    if cli is None:
        raise FileNotFoundError("kicad-cli not found — install KiCad 10 or set KICAD_CLI")
    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    r = run([str(cli), kind, "upgrade", str(src), "-o", str(dst), "--force"],
            capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise ValueError(f"kicad-cli {kind} upgrade {Path(src).name} failed: "
                         f"{(r.stderr or r.stdout or '').strip()[-500:]}")

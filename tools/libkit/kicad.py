"""Locating the KiCad installation."""

from __future__ import annotations

import os
import shutil
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

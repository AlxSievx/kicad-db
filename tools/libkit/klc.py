"""KiCad Library Convention checks via kicad-library-utils (pinned commit)."""

from __future__ import annotations

import fnmatch
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

import yaml

from .parts import Issue

KLC_REPO = "https://gitlab.com/kicad/libraries/kicad-library-utils.git"
LOCK_FILE = Path("tools") / "klc.lock"
ALLOWLIST_FILE = Path("schema") / "klc-allowlist.yaml"


def klc_dir(root: Path) -> Path:
    return Path(root) / "build" / "vendor" / "kicad-library-utils"


def fetch_klc(root: Path) -> Path:
    root = Path(root)
    commit = (root / LOCK_FILE).read_text(encoding="utf-8").strip()
    d = klc_dir(root)
    if not (d / ".git").exists():
        d.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "-q", KLC_REPO, str(d)], check=True)
    else:
        subprocess.run(["git", "-C", str(d), "fetch", "-q", "origin"], check=True)
    subprocess.run(["git", "-C", str(d), "checkout", "-q", commit], check=True)
    return d


def load_allowlist(root: Path) -> list[dict]:
    f = Path(root) / ALLOWLIST_FILE
    if not f.exists():
        return []
    with open(f, encoding="utf-8") as fh:
        entries = yaml.load(fh, Loader=yaml.BaseLoader) or []
    for e in entries:
        missing = {"kind", "item", "rule", "reason"} - set(e)
        if missing:
            raise ValueError(f"{ALLOWLIST_FILE.as_posix()}: entry {e} lacks {sorted(missing)}")
    return entries


def _allowed(kind: str, item: str, rule: str, allow: list[dict]) -> bool:
    def match(pattern) -> bool:
        pats = pattern if isinstance(pattern, list) else [pattern]
        return any(fnmatch.fnmatchcase(item, p) for p in pats)
    return any(e["kind"] == kind and e["rule"] == rule and match(e["item"]) for e in allow)


def _run(script: Path, files: list[Path], kind: str, allow: list[dict]) -> list[Issue]:
    with tempfile.TemporaryDirectory() as tmp:
        junit = Path(tmp) / "klc.xml"
        r = subprocess.run([sys.executable, str(script), "--nocolor", "-s", *map(str, files),
                            "--junit", str(junit)], capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        if not junit.exists():
            return [Issue("error", None, f"KLC {script.name} failed: {(r.stderr or r.stdout).strip()[-500:]}")]
        tree = ET.parse(junit)
    issues: list[Issue] = []
    for case in tree.iter("testcase"):
        item = case.get("name", "").rsplit(" - ", 1)[0]
        for fail in case.iter("failure"):
            rule = fail.get("message", "").split(":", 1)[0].strip()
            if _allowed(kind, item, rule, allow):
                continue
            severity = "error" if fail.get("type") == "FAILURE" else "warning"
            lines = [ln.strip() for ln in (fail.text or "").splitlines() if ln.strip()]
            detail = next((ln for ln in lines[1:] if not ln.startswith("http")), "")
            issues.append(Issue(severity, item, f"KLC {fail.get('message', rule)} — {detail}".rstrip(" —")))
    return issues


def run_klc(root: Path, files: list[Path]) -> list[Issue]:
    d = klc_dir(root) / "klc-check"
    if not d.exists():
        return [Issue("error", None, "KLC checker not installed — run `python -m libkit fetch-klc`")]
    allow = load_allowlist(root)
    syms = [f for f in files if f.suffix == ".kicad_sym"]
    fps = [f for f in files if f.suffix == ".kicad_mod"]
    issues: list[Issue] = []
    if syms:
        issues += _run(d / "check_symbol.py", syms, "symbol", allow)
    if fps:
        issues += _run(d / "check_footprint.py", fps, "footprint", allow)
    return issues

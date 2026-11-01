# JLC Assembly Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `libkit jlc-export <board.kicad_pcb>` writes JLCPCB's BOM and placement (CPL) files for a board built from LIB parts, with each part's placement corrected so JLC's machines put it down the right way round.

**Architecture:** The correction comes from where JLC's own footprint puts the part. The EasyEDA footprint of a C-number shows the orientation JLC places that part in. `placement.fit()` compares its pads with the pads of the footprint the part uses in LIB (same pad numbers, rotations 0/90/180/270) and returns a rotation and an offset. `add` stores these per part in the YAML (`jlc_rotation`, `jlc_offset`); `libkit placement` fills them in for parts added earlier. The exporter reads the board file directly (reference, footprint, side, position, rotation, LCSC property, DNP/exclude flags), looks each part up in the library by LCSC number, applies the correction, and writes two CSV files.

**Tech Stack:** Python 3.12, PyYAML, pytest, easyeda2kicad 1.0.1 (existing importer), KiCad 10.0.1 `kicad-cli pcb export pos` (only as a cross-check in tests).

**Spec:** `docs/superpowers/specs/2026-11-01-kicad-library-design.md` (§6.3 JLC rotation, §6.7 single add). Plan series: `docs/superpowers/plans/2026-11-01-library-foundation.md` (this is Plan 5).

## Findings that shaped this plan (probed 2026-11-01)

- Fitting KiCad stock footprints to the EasyEDA footprint of the same C-number (pad numbers matched, pad centres compared after removing the pad centroid):

| Part | LIB footprint | best fit | max error |
|---|---|---|---|
| C81598 1N4148W | D_SOD-123 | 0° | 0.08 mm |
| C8678 SS34 | D_SMA | 0° | 0.20 mm |
| C20917 AO3400A | SOT-23 | 180° | 0.08 mm |
| C2286 KT-0603R (LED) | LED_0603_1608Metric | 180° | 0.04 mm |
| C25744 0402 resistor | R_0402_1005Metric | 0° | 0.08 mm |
| C6186 AMS1117 | SOT-223-3_TabPin2 | no fit: EasyEDA numbers the tab 4, KiCad 2 | — |

  SOT-23 at 180° matches the community tables (JLCKicadTools, kicad-jlcpcb-tools). The LED result shows that the correction depends on the part (how the maker marks the cathode, how the reel is loaded), not only on the footprint. That is why it is stored per part, not per footprint family as spec §6.3 first assumed.
- The SOT-23 pad centroid sits 0.33 mm from the EasyEDA origin and −0.31 mm from the KiCad origin. JLC places by its own origin, so asymmetric packages also need a position offset.
- `kicad-cli pcb export pos --format csv --units mm` exists in KiCad 10. It has no LCSC column, so it can only be a cross-check for coordinates.
- KiCad 10 copies symbol fields (here `LCSC`, `MPN`) into the board footprint's properties on "Update PCB from Schematic".

## Decisions for the user to confirm (marked ⚑ in tasks)

1. ⚑ **The correction is per part**, kept in the YAML only (like `stock`): `jlc_rotation` (0/90/180/270) and `jlc_offset` (`"dx,dy"` in mm, in footprint coordinates, KiCad axes). Chip R/C/L/ferrite beads need neither: they are symmetric, so no field means 0.
2. ⚑ **`add` computes it** whenever the footprint is not EasyEDA's own: it fetches the EasyEDA footprint even for stock footprints (one more easyeda2kicad run per add). No fit → a warning, and the part is exported with 0 until someone sets the fields by hand (from JLC's placement preview).
3. ⚑ **Bottom-side parts**: rotation = (KiCad angle + correction) mod 360, X as seen from the top (not mirrored), the same as KiCad's own position file without `--bottom-negate-x`. This is the most common convention, but it is unverified for JLC: the first bottom-side order must be checked in JLC's placement preview.
4. ⚑ **Output**: `<board folder>/jlcpcb/<board>-BOM.csv` with `Comment,Designator,Footprint,LCSC Part #`, grouped by LCSC; and `<board>-CPL.csv` with `Designator,Mid X,Mid Y,Layer,Rotation` (mm, Y up, origin = the board's drill/place origin if set, else the sheet origin). JLC's documented column names.
5. ⚑ **Parts that are left out**: no `LCSC` property, DNP, `exclude_from_bom` (BOM) and `exclude_from_pos_files` (CPL) are left out and listed in the report, so mechanical parts drop out by themselves.

## Global Constraints

- All Global Constraints of Plans 1–4 still hold (UTF-8 + LF, no absolute paths in the library, `build` + `check` clean before a commit, network only in the commands that need it, tests offline).
- Network: `add` (dry run) and `placement` (dry run) only. `jlc-export` uses no network unless `--stock` is given (then it reports current JLC stock per BOM line).
- Commits: `libkit:` / `lib:` / `parts:` / `doc:` prefix, one short subject, at most two body lines, no Co-Authored-By trailer. Branch `plan5-jlc-export`, merged locally after the user's OK. Library content (the backfill of `jlc_rotation`) only after the user's OK on its table.
- Commands are PowerShell from `C:\kicad-db`; `py` means `.venv\Scripts\python`.

## Review Focus

1. **Rotations that wrap or come as floats.** A KiCad angle of `-90`, `270.0` or `359.9` with a correction of 180 must come out in [0, 360) with no `-0`. → Task 4 `test_rotation_normalised`.
2. **Offsets on rotated and bottom-side parts.** The offset must turn with the part's angle and flip with the side. Otherwise a SOT-23 at 90° lands 0.3 mm off. → Task 4 `test_offset_rotates_with_part`, `test_offset_bottom_side`.
3. **Boards with parts from outside LIB.** Stock KiCad footprints with an `LCSC` field typed by hand, or two LIB parts with the same LCSC number, must export (correction 0, or the first match) with a warning, not crash. → Task 4 `test_unknown_lcsc_warns`.
4. **Footprints whose pad numbers differ from EasyEDA's** (SOT-223 tab 2 vs 4, `MP` pads, unnumbered pads). They must give "no fit" plus a note, never a wrong rotation. → Task 1 `test_no_fit_on_number_mismatch`.
5. **Board text that breaks CSV.** A value like `10k, 1%` or `"quoted"` must stay one cell. → Task 4 `test_csv_quoting`.

---

### Task 1: Fit a footprint to JLC's footprint ⚑1

**Files:**
- Create: `tools/libkit/placement.py`
- Create fixtures: `tests/fixtures/easyeda_fp/C81598.kicad_mod`, `C20917.kicad_mod`, `C2286.kicad_mod`, `C6186.kicad_mod` (the upgraded EasyEDA footprints, recorded once with `importer.fetch_easyeda`), and the stock `D_SOD-123`, `SOT-23`, `LED_0603_1608Metric`, `SOT-223-3_TabPin2` in `tests/fixtures/share/footprints/` (3D models stripped, as in Plan 4)
- Test: `tests/test_placement.py`

**Interfaces:**
- Produces:
  - `pad_centres(fp: list) -> dict[str, tuple[float, float]]`: per non-empty pad number, the mean of its pads' `at` (KiCad mm, Y down).
  - `@dataclass Fit: rotation: int; dx: float; dy: float; error: float`.
  - `fit(lib_fp: list, jlc_fp: list, tolerance: float = 0.3) -> Fit | None`. `None` when the pad-number sets differ or no rotation in (0, 90, 180, 270) brings every pad within `tolerance` mm. `rotation` is the angle that turns the LIB footprint into JLC's orientation (counter-clockwise, KiCad convention). (`dx`, `dy`) = the JLC origin minus the LIB origin, in LIB footprint coordinates, rounded to 0.01 mm. With several equally good rotations (a symmetric 2-pad part with equal pads), prefer 0, then 180.
  - `format_offset(dx, dy) -> str` (`"0.33,0"`) / `parse_offset(text) -> tuple[float, float]`.

- [ ] **Step 1: Record the fixtures** (network, once).
- [ ] **Step 2: Write failing tests**

```python
def test_fit_sod123(): assert fit(stock("D_SOD-123"), easyeda("C81598")).rotation == 0
def test_fit_sot23(): f = fit(stock("SOT-23"), easyeda("C20917")); assert f.rotation == 180 and abs(f.dx) > 0.5  # origins 0.33 / -0.31 apart
def test_fit_led_0603(): assert fit(stock("LED_0603_1608Metric"), easyeda("C2286")).rotation == 180
def test_fit_self_is_zero(): f = fit(stock("SOT-23"), stock("SOT-23")); assert (f.rotation, f.dx, f.dy) == (0, 0, 0)
def test_no_fit_on_number_mismatch(): assert fit(stock("SOT-223-3_TabPin2"), easyeda("C6186")) is None   # Review Focus 4
def test_no_fit_beyond_tolerance(): # LIB pads scaled x2 -> None
def test_offset_roundtrip(): assert parse_offset(format_offset(0.33, -0.1)) == (0.33, -0.1)
```

- [ ] **Step 3: Run** `py -m pytest tests/test_placement.py -v`. Expected: FAIL (ImportError).
- [ ] **Step 4: Implement** `placement.py`.
- [ ] **Step 5: Run** `py -m pytest -q`. Expected: all pass.
- [ ] **Step 6: Commit** `libkit: fit LIB footprints to JLC's placement orientation`

---

### Task 2: `add` records the correction ⚑1 ⚑2

**Files:**
- Modify: `schema/library.yaml` (common fields `{key: jlc_rotation, kind: enum, choices: ["0", "90", "180", "270"]}`, `{key: jlc_offset, pattern: '-?\d+(\.\d+)?,-?\d+(\.\d+)?'}`, no `label` → YAML only), `tools/libkit/add.py`
- Test: `tests/test_add.py`

**Interfaces:**
- Consumes: `placement.fit`, `importer.fetch_easyeda` (via the `easyeda()` helper already in `prepare`).
- Produces: for non-chip parts in `prepare`:
  - EasyEDA footprint → no fields (0 by construction), note `"JLC placement: EasyEDA footprint (no correction)"`.
  - Stock or LIB footprint → fetch EasyEDA (if not fetched yet) and `fit` against the final footprint file. On a fit: `entry["jlc_rotation"]` (always) and `entry["jlc_offset"]` (only when not `0,0`), note `"JLC placement: rotate <r>°, offset <dx>,<dy> mm (from EasyEDA <LCSC>)"`. No fit or no EasyEDA footprint → warning `"no JLC placement correction: … — set jlc_rotation/jlc_offset from JLC's placement preview"`.
  - `--local` parts and chip passives: nothing.

- [ ] **Step 1: Write failing tests** (fake `fetch` returns the recorded EasyEDA footprints)

```python
def test_add_records_rotation(lib): p = prep(lib, "C20917", **SOT23); assert p.entry["jlc_rotation"] == "180" and "jlc_offset" in p.entry
def test_add_led_rotation(lib): assert prep(lib, "C2286", **LED0603)["entry"]... == "180"
def test_add_easyeda_footprint_no_fields(lib): p = prep(lib, "C6186", **IC); assert "jlc_rotation" not in p.entry
def test_add_no_fit_warns(lib): # stock SOT-223 for C6186 -> warning "no JLC placement correction"
def test_jlc_fields_not_in_symbol(lib): # after apply: symbols/LIB_Transistors.kicad_sym has no "jlc_rotation"/"JLC" property
```

- [ ] **Step 2: Run** `py -m pytest tests/test_add.py -v`. Expected: the new tests FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `py -m pytest -q`; `py -m libkit build; py -m libkit check`. Expected: all pass, 0 errors.
- [ ] **Step 5: Commit** `libkit: add records the JLC placement correction`

---

### Task 3: `libkit placement` for parts added earlier

**Files:**
- Modify: `tools/libkit/placement.py`, `tools/libkit/__main__.py`
- Test: `tests/test_placement.py`

**Interfaces:**
- Produces:
  - `plan_backfill(root, *, fetch=None) -> list[Backfill]` (`Backfill: name, lcsc, footprint, rotation: int | None, offset: str | None, note: str`) for every orderable non-chip part without `jlc_rotation`: fetch EasyEDA, fit, or a note why not. Saved as `.libkit/placement-plan.json` (same 24 h / unchanged-library rules as `bulk-add`).
  - `apply_backfill(root, rows) -> int`: writes the fields of the rows with a rotation, then builds.
  - CLI `libkit placement` (dry run: table name / LCSC / footprint / rotation / offset / note) and `libkit placement --write`.

- [ ] **Step 1: Write failing tests** (`test_backfill_plan_rows`, `test_backfill_skips_chip_passives_and_local`, `test_backfill_write_applies_exact_plan`, `test_backfill_refuses_changed_library`)
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `py -m pytest -q`. Expected: all pass.
- [ ] **Step 5: Commit** `libkit: placement backfill for existing parts`

---

### Task 4: Board reader and JLC files ⚑3 ⚑4 ⚑5

**Files:**
- Create: `tools/libkit/board.py`, `tools/libkit/jlcexport.py`
- Create fixture: `tests/fixtures/boards/demo.kicad_pcb`: a small KiCad 10 board saved by KiCad, with R (0402, top, 0°), D (SOD-123, top, 90°), Q (SOT-23, bottom, 30°), an LED, a part without LCSC, a DNP part, a mounting hole (excluded from BOM and position files), and a drill/place origin. It is written by hand in KiCad 10's board format (footprints copied from LIB), and counts as valid once `kicad-cli pcb export pos` reads it without error.
- Modify: `tools/libkit/__main__.py` (`jlc-export`)
- Test: `tests/test_jlcexport.py`

**Interfaces:**
- Produces:
  - `@dataclass BoardPart: ref, lib_id, value, lcsc, side ("top"/"bottom"), x, y, angle: float, dnp, no_bom, no_pos: bool`.
  - `read_board(path: Path) -> tuple[list[BoardPart], tuple[float, float]]`: the footprints and the place origin (`(setup (aux_axis_origin x y))`, else `(0, 0)`). Properties come from `(property "LCSC" …)` (case-insensitive name). Flags come from `(attr … dnp exclude_from_bom exclude_from_pos_files)` and `(property "dnp" …)` as KiCad 10 writes them; confirm the format on the fixture.
  - `export(root: Path, board: Path, out_dir: Path) -> Report` (`Report: bom_lines, placed, skipped: list[str], warnings: list[str]`):
    - **BOM:** grouped by LCSC; `Comment` = the LIB part's `value` (else the board value); `Footprint` = footprint name without library; designators naturally sorted (`R2` before `R10`).
    - **CPL:** `Mid X` = x − origin x; `Mid Y` = −(y − origin y). The offset (dx, dy) is turned by the footprint angle and mirrored in X for bottom-side parts, then added in board coordinates before the axis change. `Rotation` = (angle + jlc_rotation) mod 360 on both sides (⚑3). Numbers are written with up to 4 decimals and no trailing zeros, layer `Top`/`Bottom`.
    - **Warnings:** LCSC not in the library ("no correction"); the same LCSC on two LIB parts; Extended parts (count; JLC charges a feeder fee).
  - CLI: `libkit jlc-export <board> [-o DIR] [--stock]` prints the report and the two file paths.

- [ ] **Step 1: Write the fixture board.** Run `kicad-cli pcb export pos` on it. Expected: exit 0, with every placed part listed.
- [ ] **Step 2: Write failing tests**

```python
def test_read_board(): parts, origin = read_board(DEMO); # refs, sides, angles, lcsc, flags as placed in the fixture
def test_bom_grouped_and_sorted(tmp_path): # one line per LCSC, "R1,R2,R10", DNP and no-LCSC parts absent and listed in report.skipped
def test_cpl_origin_and_y_up(tmp_path): # resistor at board (110, 80) with origin (100, 100) -> Mid X 10, Mid Y 20
def test_rotation_normalised(): assert jlc_angle(-90, 180) == 90 and jlc_angle(270.0, 180) == 90 and jlc_angle(180, 180) == 0   # Review Focus 1
def test_offset_rotates_with_part(): # SOT-23 offset (0.64, 0) at angle 90 top -> board shift (0, -0.64)  (Review Focus 2)
def test_offset_bottom_side(): # same offset on bottom at 0° -> X mirrored  (Review Focus 2)
def test_unknown_lcsc_warns(tmp_path): # LCSC typed on a stock footprint -> exported, rotation unchanged, warning names it  (Review Focus 3)
def test_csv_quoting(tmp_path): # value '10k, 1% "x"' -> csv.reader reads one cell back unchanged  (Review Focus 5)
@pytest.mark.kicad
def test_positions_match_kicad_cli(tmp_path): # for parts without correction, our Mid X/Y/Rotation == kicad-cli pcb export pos --format csv --units mm --use-drill-file-origin (Y sign per kicad-cli), within 0.001
```

- [ ] **Step 3: Run** `py -m pytest tests/test_jlcexport.py -v`. Expected: FAIL (ImportError).
- [ ] **Step 4: Implement** `board.py`, `jlcexport.py` and the CLI.
- [ ] **Step 5: Run** `py -m pytest -q`. Expected: all pass.
- [ ] **Step 6: Commit** `libkit: JLC BOM and placement export`

---

### Task 5: Docs, backfill, real-board check

- [ ] **Step 1: Docs.** `CLAUDE.md`: commands (`placement`, `jlc-export`), a workflow paragraph ("Ordering at JLC"), the new YAML fields under Rules. Spec §6.3: a "Decided (Plan 5)" paragraph (per-part correction from EasyEDA, ⚑1–⚑5). Plan series: Plan 5 done. Commit `doc: JLC assembly export`.
- [ ] **Step 2: Backfill** (network): `py -m libkit placement`; show the user the table; `--write` only after their OK; `build`, `check`, commit `parts: JLC placement corrections`.
- [ ] **Step 3: Real board** (user): export a real board and upload both files to JLC's assembly quote. Check every polarised part (diodes, LEDs, SOT-23) and one bottom-side part in JLC's placement preview. Record the result in the spec paragraph; a wrong convention becomes a fix with a test.
- [ ] **Step 4: Final review** of the whole branch by one fresh reviewer; fixes in `libkit: final review fixes`; ask the user before merging.

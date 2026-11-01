# Single-Part Add Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Claude can add any single part from an LCSC C-number or MPN through `python -m libkit add` (passives incl. inductors and ferrite beads, ICs, connectors…), with a symbol, footprint and 3D model normalised to the library's style, and can list candidates for a value with `python -m libkit find`.

**Architecture:** `add` works like `bulk-add`. The dry run resolves the part at JLC and builds the YAML entry. It stages the symbol, footprint and STEP model in `.libkit/add/<REF>/` and runs KLC on what it staged. It prints a report and saves the plan. `--write` applies exactly that plan, with no network access, and rolls back on failure. Chip passives use the base symbols and `LIB_Passives_SMD` footprints. Other parts take each of their symbol and footprint from one of three sources: KiCad's stock library (preferred, since those already pass KLC), easyeda2kicad output, or a part already in LIB. easyeda2kicad output is first upgraded to the KiCad 10 format with `kicad-cli`, then normalised by pure functions over s-expressions.

**Tech Stack:** Python 3.12, PyYAML, pytest, easyeda2kicad 1.0.1 (run as a subprocess), KiCad 10.0.1 `kicad-cli` (`sym upgrade`, `fp upgrade`, `sym/fp export svg`), kicad-library-utils (KLC).

**Spec:** `docs/superpowers/specs/2026-11-01-kicad-library-design.md` (§6.5 symbols, §6.6 rules, §6.7 single add, §6.3 footprints, §6.8 checks). Plan series: `docs/superpowers/plans/2026-11-01-library-foundation.md` (this is Plan 3).

## Findings that shaped this plan (probed 2026-11-01)

- `easyeda2kicad 1.0.1` (AGPL-3.0, no dependencies) installs and runs on Python 3.12. The command is `python -m easyeda2kicad --full --lcsc_id C6186 --output <dir>/E2K`, and `<dir>` must already exist. It writes:
  - `E2K.kicad_sym`: symbol format `20211014`, every pin `unspecified`, outline width 0, extra properties `Manufacturer`, `MPN`, `LCSC Part`;
  - `E2K.pretty/<name>.kicad_mod`: old `(module …)` format, silk width 0.15, no F.Fab drawing, `rect` pads, junk on `Cmts.User`. The courtyard covers **only the body, not the pads**;
  - `E2K.3dshapes/<model>.step` and `.wrl`: STEP files are 1–3 MB, and the model has `(rotate (xyz 0 0 180))`.
  - EasyEDA names are not KLC names (`SOT-223-3_L6.5-W3.4-P2.30-LS7.0-BR`).
- `kicad-cli sym upgrade <in> -o <out>` and `kicad-cli fp upgrade <dir.pretty> -o <out.pretty>` convert this output to the KiCad 10 format (`20251024` / `20260206`), and `%R` becomes `${REFERENCE}`.
- KLC on the upgraded EasyEDA output reports:
  - footprint: F5.1 (silk width), F5.2 (no fab), F6.3 (rect pads), F9.1 (no descr/tags), F9.3 (model; already allow-listed for `*`);
  - symbol: S3.3 (outline width), S4.2 (ground pin not at the bottom), S4.4 (pin types), and S5.1/S5.2/S6.2 (allow-listed).
- JLC search (`selectSmtComponentList`) accepts `pageSize: 100` and keywords like `"10uH 0805"` (209 hits) or an MPN, and returns `total`. Results come in C-number order, not by stock.
- Inductor attributes: `Inductance` "10uH", `Current Rating` "15mA" / "3.2A", `DC Resistance(DCR)` "1.15Ω", and saturation current spelled **both** `Current - Saturation (Isat)` and `Current - Saturation(Isat)`. Missing values are `"-"`.
- Ferrite beads (C1015): `Impedance @ Frequency` "100Ω@100MHz", `Current Rating` "800mA", `DC Resistance(DCR)` "150mΩ", no `Inductance`.
- Power inductors have packages like `SMD,5.4x5.2mm`, so they need a footprint from easyeda or KiCad stock.

## Decisions for the user to confirm (marked ⚑ in tasks)

1. ⚑ **Ferrite beads** go in Inductors as `FB_<impedance>_<pkg>_<current>` (`FB_100R_0805_800mA`), with value `100R@100MHz`, symbol `FerriteBead` and an explicit description `… ferrite bead`.
2. ⚑ **Chip inductors** (0402–1206) are named `L_<value w/o H>_<pkg>_<current>` (`L_10u_0805_15mA`). **Power inductors** (any other package) are named by MPN, with value `10uH`.
3. ⚑ **Source preference** for non-passives: if KiCad's stock library has the symbol or footprint, Claude vendors it (`stock:<Lib>:<Name>`); otherwise Claude imports from EasyEDA and normalises. Claude picks the KLC footprint name (`--fp-name`) and the family.
4. ⚑ **EasyEDA footprints keep EasyEDA's orientation**, which is JLC's placement orientation; there is no automatic rotation to KLC's pin-1-top-left. The report notes when they differ.
5. ⚑ **STEP only** (WRL dropped), at 1–3 MB per new package in git.
6. ⚑ **Unknown brands on single adds** are kept as the brand string with any `(…)` suffix removed, and the report warns. They are **not** added to `manufacturers:`, which stays the list for automatic picks.

## Global Constraints

- All Global Constraints of Plans 1 and 2 still hold: UTF-8 + LF, no absolute paths, names never renamed or reused, stock never written into symbols, `build` + `check` clean before a commit, and network use only in the commands that need it.
- Selection rules (spec §6.6), verbatim: 1. JLC **Basic or Preferred** before Extended; Extended only if nothing fits. 2. Stock: **≥ ~1000 for bulk-added passives**. For single parts I name myself: any stock > 0 is accepted, with a warning below ~100. 3. **Known manufacturers only** (…). 4. Ceramic capacitors: **C0G/NP0, X7R or X5R**, never Y5V/Z5U. 5. Bulk adds show the full list for confirmation before anything is written. 6. English datasheet preferred within the same JLC tier.
- Network is used only by `jlc`, `bulk-add` (dry run), `refresh-stock`, `find` and `add` (dry run). `add --write` uses no network. Tests never touch the network or run easyeda2kicad. Tests that need `kicad-cli` carry `@pytest.mark.kicad` and skip when it is missing.
- Part names: KLC G1.1 characters only (`[A-Za-z0-9_.+,-]`). An MPN containing other characters gets each run of them replaced by `_`.
- Footprint style, with values from KLC: silk 0.12 mm; fab 0.10 mm; courtyard 0.05 mm at 0.25 mm clearance on a 0.01 mm grid; Reference on F.SilkS (1.0 mm, 0.15 thick); Value = footprint name on F.Fab; `${REFERENCE}` on F.Fab; SMD pads `roundrect` with a radius of 25 % of the shorter side, at most 0.25 mm.
- Symbol style (spec §6.5): 100 mil pin grid, 1.27 mm text, outline 0.254 mm, the fixed field order from `symgen.STANDARD`, and only Reference + Value visible.
- 3D paths: `${LIB_DIR}/3dmodels/LIB_<Family>.3dshapes/<footprint name>.step`.
- `requirements.txt` pins `easyeda2kicad==1.0.1`.
- Commits: `libkit:` / `lib:` / `parts:` / `doc:` prefix, short subject, **no Co-Authored-By trailer**. Work on branch `plan3-single-add` and merge locally. Commit library content only after the user's OK.
- Commands are PowerShell from `C:\kicad-db`; `py` means `.venv\Scripts\python`.

## Review Focus

1. **JLC attribute spelling drift.** `Current - Saturation (Isat)` and `…(Isat)` (no space), `"-"` for missing values, and `℃`/`Ω`/`µ` must all produce the same entry. → Task 2 `test_attr_key_variants`.
2. **MPNs that are not valid names.** `CKCS4018-4.7uH/M` and `CD31 4R7M 4.7UH` must become valid names. A collision with any existing name, including a deprecated one, must be refused, not overwritten. → Task 2 `test_mpn_name_sanitized`, Task 7 `test_add_refuses_existing`.
3. **Multi-unit and derived symbols.** Renaming must rename every unit sub-symbol `<old>_<u>_<s>`. A stock symbol that `extends` a parent must come out flattened, because `build` cannot resolve `extends` for a unique symbol. → Task 5 `test_rename_multi_unit`, `test_flatten_stock_extends`.
4. **Footprints that are not plain SMD.** THT pads (no roundrect conversion, keep `*.Cu`), no 3D model (no `model` node, a note), and pads that already are `roundrect` must all normalise without errors. → Task 4 `test_tht_pads_untouched`, `test_no_model`.
5. **A failed `--write` leaves no partial state.** When `build` fails after the files are copied, every touched file is restored and every new one is deleted, including the `schema/library.yaml` family line. → Task 7 `test_apply_rolls_back`.

---

### Task 1: JLC keyword search and MPN resolution

**Files:**
- Modify: `tools/libkit/jlc.py`, `tests/fakes.py` (`paged_fake(fname)`: answers page 1 from the file, fails the test on any later page)
- Create fixtures: `tests/fixtures/jlc/search_10uH_0805.json` (page 1, trimmed to 20 records), `mpn_AMS1117-3.3.json`, `C1046.json`, `C1015.json`, `C408412.json`
- Test: `tests/test_jlc.py`

**Interfaces:**
- Produces:
  - `jlc.search(keyword: str, *, pages: int = 3, post=None) -> list[JlcPart]`: `pageSize` 100, pages 1..`pages`; it stops early when a page is short; records are parsed with `parse_record`.
  - `jlc.resolve(ref: str, post=None) -> JlcPart`:
    - a `C\d+` ref → `lookup`, and `ValueError("C…: not found at JLC")` on `None`;
    - otherwise `search(ref, pages=1)` filtered by a case-insensitive exact `mpn` match. No match → `ValueError("no JLC part with MPN …")`; several → `ValueError` listing `C… (stock, type)` for each, so Claude can pick by C-number.

- [ ] **Step 1: Record fixtures.** Use live POSTs (keyword `10uH 0805` page 1; keyword `AMS1117-3.3`; the three C-numbers). Save them pretty-printed as UTF-8 and trim the search list to 20 records.
- [ ] **Step 2: Write failing tests**

```python
def test_search_parses_pages(): parts = search("10uH 0805", pages=2, post=paged_fake("search_10uH_0805.json"))
    # len(parts) == 20 (short page stops paging; fake asserts page 2 is never requested), "C1046" in [p.lcsc for p in parts]
def test_resolve_c_number(): assert resolve("C1046", post=fake_post("C1046.json")).mpn == "SDFL2012S100KTF"
def test_resolve_mpn_exact(): assert resolve("ams1117-3.3", post=fake_post("mpn_AMS1117-3.3.json")).lcsc == "C6186"
def test_resolve_mpn_ambiguous(): with pytest.raises(ValueError, match="C"): resolve(<mpn with two records>, post=...)
def test_resolve_not_found(): with pytest.raises(ValueError, match="not found"): resolve("C999999999", post=fake_post("notfound.json"))
```

- [ ] **Step 3: Run** `py -m pytest tests/test_jlc.py -v`. Expected: the new tests FAIL (ImportError).
- [ ] **Step 4: Implement** `search` and `resolve`.
- [ ] **Step 5: Run** `py -m pytest -q`. Expected: all pass.
- [ ] **Step 6: Commit** `libkit: JLC keyword search and MPN resolution`

---

### Task 2: Inductor and ferrite-bead entries, MPN names ⚑1 ⚑2 ⚑6

**Files:**
- Modify: `tools/libkit/entries.py`
- Test: `tests/test_entries.py`

**Interfaces:**
- Consumes: `JlcPart`, `jlc.parse_record`, `values.format_value/parse_value`, `Schema.canonical_manufacturer`.
- Produces:
  - `KINDS` gains `"inductor": ("inductors", "L", "H", "L")` and `"bead": ("inductors", "FerriteBead", "Ω", "L")`.
  - `kind_of(part: JlcPart) -> str | None`. It returns `None` for arrays (`_array`). Otherwise it checks the attributes in this order: `Resistance` → `"resistor"`, `Capacitance` → `"capacitor"`, `Impedance @ Frequency` → `"bead"`, `Inductance` → `"inductor"`. `None` when none matches.
  - `_attr(part, *keys, required=True)` matches attribute names with whitespace removed and case folded, and treats `"-"` and `""` as missing.
  - `passive_name(...)` gains `current: str | None = None`:
    - inductor → `L_10u_0805_15mA`;
    - bead → `FB_100R_0805_800mA` (impedance formatted with unit `Ω`; current = JLC text without spaces).
  - `mpn_name(mpn: str) -> str`: each run of characters outside `[A-Za-z0-9_.+,-]` becomes `_`, with leading and trailing `_` stripped.
  - `manufacturer_name(brand: str, schema: Schema) -> tuple[str, bool]`: `(canonical, True)`, or `(brand without a "(…)" suffix, stripped, False)`.
  - `passive_entry(kind, part, schema, today=None, *, footprint: str | None = None, known_only: bool = True) -> dict[str, str]`:
    - `known_only=False` uses `manufacturer_name` instead of raising.
    - The package is in `METRIC` → pattern name and `footprint_for`. Otherwise `footprint` is required (`ValueError` if missing), and name = `mpn_name(part.mpn)`.
    - Inductor fields: `current_rating` ← `Current Rating`; `current_sat` ← `Current - Saturation (Isat)` (optional); `dcr` ← `DC Resistance(DCR)` (optional).
    - Bead: `value` = `100R@100MHz`, `current_rating`, `dcr`, `description` = `"<value> <current> <package> ferrite bead"`.

- [ ] **Step 1: Write failing tests**

```python
def test_kind_of(): assert [kind_of(parse_record(rec(c))) for c in ("C25744","C1525","C1046","C1015")] == ["resistor","capacitor","inductor","bead"]
def test_inductor_entry(schema):
    e = passive_entry("inductor", parse_record(rec("C1046")), schema)
    # e["name"] == "L_10u_0805_15mA", e["value"] == "10uH", e["symbol"] == "L",
    # e["footprint"] == "LIB_Passives_SMD:L_0805_2012Metric", e["dcr"] == "1.15Ω", "current_sat" not in e, validate → no errors
def test_bead_entry(schema):
    e = passive_entry("bead", parse_record(rec("C1015")), schema)
    # e["name"] == "FB_100R_0805_800mA", e["value"] == "100R@100MHz", e["symbol"] == "FerriteBead",
    # e["description"] == "100R@100MHz 800mA 0805 ferrite bead"
def test_power_inductor_needs_footprint(schema):
    with pytest.raises(ValueError, match="footprint"): passive_entry("inductor", parse_record(rec("C408412")), schema)
    e = passive_entry("inductor", parse_record(rec("C408412")), schema, footprint="LIB_Inductor_SMD:L_Sunlord_MWSA0503S")
    # e["name"] == "MWSA0503S-100MT", e["current_sat"] == "3.5A"
@pytest.mark.parametrize("key", ["Current - Saturation (Isat)", "Current - Saturation(Isat)", "current - saturation(isat)"])
def test_attr_key_variants(schema, key): ...   # Review Focus 1: same current_sat; "-" → field absent; "℃" → "°C"
@pytest.mark.parametrize("mpn,name", [("CKCS4018-4.7uH/M","CKCS4018-4.7uH_M"), ("CD31 4R7M 4.7UH","CD31_4R7M_4.7UH"), ("TPS62130RGTR","TPS62130RGTR")])
def test_mpn_name_sanitized(mpn, name): assert mpn_name(mpn) == name     # Review Focus 2
def test_unknown_brand_single_add(schema): assert manufacturer_name("AMS(Advanced Monolithic Systems)", schema) == ("AMS", False)
```

- [ ] **Step 2: Run** `py -m pytest tests/test_entries.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement.** Existing resistor and capacitor behaviour and every Plan 2 test stay unchanged.
- [ ] **Step 4: Run** `py -m pytest -q`. Expected: all pass.
- [ ] **Step 5: Commit** `libkit: inductor and ferrite bead entries, names from MPNs`

---

### Task 3: `find` command (candidates for one value)

**Files:**
- Create: `tools/libkit/find.py`
- Modify: `tools/libkit/__main__.py`
- Test: `tests/test_find.py`

**Interfaces:**
- Consumes: `jlcsearch.resistors/capacitors`, `jlc.search`, `jlc.lookup`, `entries.kind_of/passive_entry`, `pick.LANG_RANK` ordering ideas (no language check in `find`).
- Produces:
  - `@dataclass Option(part: JlcPart, entry: dict | None, notes: list[str])`
  - `find(root: Path, kind: str, value: float, package: str, *, max_tolerance: float | None = None, min_voltage: float | None = None, dielectrics: tuple[str, ...] = ("C0G","NP0","X7R","X5R"), limit: int = 10, get=None, post=None, lookup=None) -> list[Option]`
    - Resistors and capacitors: jlcsearch candidates, then the hard filters (tolerance, voltage, dielectric, stock > 0), then sort (Basic/Preferred first, then stock descending), then `lookup` the first `limit`.
    - Inductors and beads: `jlc.search(f"{format_value(value, unit)} {package}")`, filtered by `kind_of == kind`, value within 0.5 % (bead: impedance), `package` and stock > 0, with the same sort.
    - `entry` = `passive_entry(kind, part, schema, known_only=False)`, or `None` with the error text as a note.
    - Notes: `Extended`, `stock < 1000`, `unknown manufacturer <brand>`, `in library as <name>` (by LCSC or name).
  - CLI: `python -m libkit find <resistor|capacitor|inductor|bead> <value> --package P [--tolerance 1%] [--voltage 25V] [--dielectric …] [--limit 10]`. It prints a table with the columns LCSC · MPN · manufacturer · type · stock · tol · V/current · dielectric/DCR · name · notes. Exit 0, also when there are no rows ("no candidates").

- [ ] **Step 1: Write failing tests** (fakes from the Task 1 and Plan 2 fixtures)

```python
def test_find_resistor_orders_by_rules(minilib): opts = find(minilib, "resistor", 10000, "0402", max_tolerance=0.01, get=..., lookup=...)
    # opts[0].part.jlc_type in ("Basic","Preferred"); stocks of same-tier rows descending; len(opts) <= 10
def test_find_marks_existing(minilib): # C25744 placed into minilib parts → its option has note "in library as R_10k_0402_1pct"
def test_find_keeps_low_stock_and_unknown_brand(minilib): # stock 50, brand "NoName" → listed, notes contain "stock < 1000" and "unknown manufacturer NoName"
def test_find_inductor(minilib): opts = find(minilib, "inductor", 10e-6, "0805", post=paged_fake("search_10uH_0805.json"))
    # every opts[i].part.package == "0805"; "C1046" first (only Basic); no bead or 0 stock rows
```

- [ ] **Step 2: Run** `py -m pytest tests/test_find.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** `find.py` and the CLI.
- [ ] **Step 4: Run** `py -m pytest -q`, then live `py -m libkit find resistor 62k --package 0402 --tolerance 1%` and `py -m libkit find inductor 10u --package 0805`. Expected: tests pass, and both tables are printed with notes.
- [ ] **Step 5: Commit** `libkit: find command lists candidates for one value`

---

### Task 4: Footprint normaliser

**Files:**
- Create: `tools/libkit/normfp.py`
- Create fixtures: `tests/fixtures/easyeda/C6186/raw/…` (easyeda2kicad output for C6186, with the `.step` replaced by a 1-line stub), `tests/fixtures/easyeda/C6186/up/E2K.pretty/*.kicad_mod` and `up/E2K.kicad_sym` (after `kicad-cli … upgrade`), `tests/fixtures/easyeda/tht.kicad_mod` (a small hand-made footprint with 2 THT pads, one roundrect SMD pad and no model)
- Test: `tests/test_normfp.py`

**Interfaces:**
- Consumes: `sexpr.parse/dumps/find/find_all/Sym`.
- Produces: `normalize_footprint(fp: list, *, name: str, lib: str, model: str | None, description: str, tags: str) -> tuple[list, list[str]]`. `lib` is the family's `lib_name`, `model` a file name in `3dmodels/<lib>.3dshapes/` or `None`, and the result is the new tree plus notes for the report. Rules, in this order:
  1. Footprint name → `name`. `version`/`generator` stay as written by `kicad-cli`, except `generator` "libkit". `descr` and `tags` are set.
  2. Properties: only `Reference`, `Value`, `Datasheet`, `Description` remain. Value = `name`, on F.Fab. Reference on F.SilkS with size 1 1 and thickness 0.15.
  3. Graphics on layers other than `F/B.SilkS`, `F/B.Fab` and `F/B.CrtYd` are dropped. Silk width becomes 0.12, fab width 0.10.
  4. No F.Fab graphics → the silk graphics are copied to F.Fab at width 0.10, with the note `fab outline copied from silkscreen — check against the package drawing`.
  5. `${REFERENCE}` text on F.Fab at the bbox centre of F.Fab, size `s = clamp(0.4 × shorter fab side, 0.5, 1.0)` rounded to 0.01, thickness `0.15 × s`. An existing one is replaced.
  6. Courtyard: all `*.CrtYd` items are removed. A new `fp_rect` on F.CrtYd, width 0.05, covers the bbox of all pads and fab items plus 0.25 mm, rounded outward to 0.01 mm. If KLC's F5.3 does not accept `fp_rect`, use 4 `fp_line`s instead (verify in Step 4).
  7. SMD `rect` pads become `roundrect` with `roundrect_rratio = min(0.25, 0.25 / min(w, h))`, rounded to 4 decimals. THT and already-round pads are untouched.
  8. Model: keep the first `model` node with its path set to `${LIB_DIR}/3dmodels/<lib>.3dshapes/<model>` and its offset/scale/rotate kept. Others are dropped. With `model=None`, all are dropped and the note is `no 3D model`.
  9. Note when pad "1" is not in the top-left quadrant: `orientation: pin 1 is not top-left (EasyEDA/JLC orientation kept)`.

- [ ] **Step 1: Record fixtures.** Run easyeda2kicad and the two `kicad-cli upgrade`s for C6186 in a scratch dir (see Findings), copy the files in and stub the STEP.
- [ ] **Step 2: Write failing tests**

```python
def test_footprint_rules(): fp, notes = normalize_footprint(load_up_fp("C6186"), name="SOT-223-3_TabPin2", lib="LIB_Package_TO_SOT",
                                                           model="SOT-223-3_TabPin2.step", description="d", tags="t")
    # fp[1] == "SOT-223-3_TabPin2"; no node on "Cmts.User"; no property "LCSC Part"; all F.SilkS widths == 0.12
    # F.Fab has lines (copied) and "fab outline copied" in notes; one fp_text user "${REFERENCE}" on F.Fab
    # courtyard rect contains every pad's extent + 0.25, coordinates are multiples of 0.01
    # all 4 pads are roundrect, rratio for the 1.1 mm pad == 0.2273, for 2.34 mm == 0.1068
    # model path == "${LIB_DIR}/3dmodels/LIB_Package_TO_SOT.3dshapes/SOT-223-3_TabPin2.step", rotate kept (0 0 180)
    # "orientation" in " ".join(notes)
def test_tht_pads_untouched(): ...   # Review Focus 4: thru_hole pads keep shape and layers "*.Cu" "*.Mask"; roundrect pad unchanged
def test_no_model(): fp, notes = normalize_footprint(..., model=None) → no "model" node, "no 3D model" in notes
@pytest.mark.kicad
def test_normalised_footprint_passes_klc(tmp_path): # write to tmp .pretty, run klc.run_klc with the repo allowlist
    # no F5.1, F5.2, F5.3, F6.3, F9.1 issues remain
```

- [ ] **Step 3: Run** `py -m pytest tests/test_normfp.py -v`. Expected: FAIL.
- [ ] **Step 4: Implement** `normfp.py`, then run the KLC test (needs `fetch-klc`) and settle rule 6's `fp_rect` question.
- [ ] **Step 5: Run** `py -m pytest -q`. Expected: all pass.
- [ ] **Step 6: Commit** `libkit: normalise imported footprints to the library style`

---

### Task 5: Symbol normaliser and stock-symbol flattening

**Files:**
- Create: `tools/libkit/normsym.py`
- Modify: `tools/libkit/vendor.py` (add `stock_symbol`)
- Create fixture: `tests/fixtures/easyeda/dual.kicad_sym` (hand-made: a 2-unit symbol `OPA_X` with sub-symbols `OPA_X_0_1`, `OPA_X_1_1` and `OPA_X_2_1`, plus `CHILD` that `extends` `OPA_X`)
- Test: `tests/test_normsym.py`

**Interfaces:**
- Produces:
  - `rename_symbol(sym: list, name: str) -> list`: renames the symbol and every child `symbol` named `<old>_<u>_<s>`.
  - `normalize_symbol(sym: list, name: str, pin_types: dict[str, str] | None = None) -> tuple[list, list[str]]`:
    1. `rename_symbol`.
    2. Only the properties in `symgen.STANDARD` remain, with empty values (build fills them in); `ki_keywords` and `ki_fp_filters` are dropped.
    3. Every font size becomes 1.27 1.27.
    4. `rectangle`/`polyline`/`circle`/`arc` with stroke width 0 → 0.254.
    5. Grid: when every pin's `at` x and y share one offset modulo 2.54 (to 0.001), all graphics, pins and property positions shift by minus that offset. Mixed offsets → a note `pins off the 100 mil grid: …`.
    6. Pin types:
       - first `pin_types` (keys are a pin name or `#<number>`, values are KiCad types such as `input`, `power_out`);
       - then, for pins still `unspecified`: `^(GND|[AP]GND|VSS|EP)\d*$` → `power_in`; `^(VCC|VDD|VIN|VBAT|V\+|AVDD|DVDD)\w*$` → `power_in`; `^VOUT\w*$` → `power_out`; `^(NC|DNC)$` → `no_connect`;
       - the rest → a note `pin types unknown: EN(#1), FB(#3) — pass --pin-types`.
  - `vendor.stock_symbol(ref: str, kicad_share: Path, name: str) -> list`: the stock symbol flattened (when it `extends` a parent, the parent's units, pins and graphics are used with the child's properties), then `rename_symbol` and empty property values.

- [ ] **Step 1: Write failing tests**

```python
def test_easyeda_symbol_rules(): sym, notes = normalize_symbol(load_up_sym("C6186", "AMS1117-3.3"), "AMS1117-3.3")
    # property names == STANDARD; no "LCSC Part"; rectangle stroke width "0.254"; every pin x,y % 2.54 == 0
    # pin types: GND → power_in, VIN → power_in, both VOUT → power_out; no "pin types unknown" note
def test_pin_types_override(): normalize_symbol(..., pin_types={"VIN": "power_in", "#4": "passive"}) → pin 4 "passive"
def test_unknown_pin_types_noted(): symbol with pins EN, FB → note lists "EN(#1)" and "FB(#3)"
def test_rename_multi_unit(): s = rename_symbol(dual["OPA_X"], "LM358DR")       # Review Focus 3
    # [c[1] for c in find_all(s, "symbol")] == ["LM358DR_0_1", "LM358DR_1_1", "LM358DR_2_1"]
def test_flatten_stock_extends(tmp_share): s = stock_symbol("Test:CHILD", tmp_share, "PART1")   # Review Focus 3
    # find(s, "extends") is None; the units are named PART1_*; the child's Reference/Description properties are kept (values emptied)
```

- [ ] **Step 2: Run** `py -m pytest tests/test_normsym.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** `normsym.py` and `vendor.stock_symbol`.
- [ ] **Step 4: Run** `py -m pytest -q`. Expected: all pass.
- [ ] **Step 5: Commit** `libkit: normalise imported symbols, flatten stock symbols`

---

### Task 6: Import sources (easyeda2kicad, kicad-cli upgrade, stock footprints)

**Files:**
- Create: `tools/libkit/importer.py`
- Modify: `tools/libkit/kicad.py` (`upgrade`), `tools/libkit/vendor.py` (`vendor_footprint` gains `dest_dir: Path | None = None`, `models_dir: Path | None = None`, `model_lib: str | None = None`), `requirements.txt`, `pyproject.toml` (dependency `easyeda2kicad`)
- Test: `tests/test_importer.py`

**Interfaces:**
- Produces:
  - `kicad.upgrade(kind: str, src: Path, dst: Path, run=subprocess.run) -> None`:
    - `kind` is `"sym"` or `"fp"`; it runs `kicad-cli <kind> upgrade <src> -o <dst> --force`.
    - `FileNotFoundError("kicad-cli not found …")` when KiCad is not installed; `ValueError` with the stderr tail on a non-zero exit.
  - `@dataclass Fetched(symbol: list | None, footprint: list | None, footprint_name: str | None, step: Path | None)`
  - `importer.fetch_easyeda(lcsc: str, workdir: Path, run=subprocess.run, upgrade=kicad.upgrade) -> Fetched`:
    - runs `[sys.executable, "-m", "easyeda2kicad", "--full", "--lcsc_id", lcsc, "--output", str(workdir / "E2K")]` with `cwd=workdir`, timeout 120 s;
    - upgrades the outputs into `workdir/up/`;
    - parses the first symbol and the single footprint.
    - Nothing written → `NetError("<lcsc>: easyeda2kicad produced no files: <stderr tail>")`.
  - `vendor_footprint(...)` with `dest_dir`/`models_dir` writes into staging instead of the library. `model_lib` is the family `lib_name` used in the rewritten `${LIB_DIR}` path. The default behaviour is unchanged (`vendor-fp` keeps working).

- [ ] **Step 1: Write failing tests**

```python
def test_fetch_easyeda_offline(tmp_path):  # fake run copies tests/fixtures/easyeda/C6186/raw into workdir; fake upgrade copies .../up
    f = fetch_easyeda("C6186", tmp_path, run=fake_run, upgrade=fake_upgrade)
    # str(f.symbol[1]) == "AMS1117-3.3"; f.footprint_name == "SOT-223-3_L6.5-W3.4-P2.30-LS7.0-BR"; f.step.suffix == ".step"
def test_fetch_easyeda_nothing_written(tmp_path): with pytest.raises(NetError, match="C6186"): fetch_easyeda(..., run=returns_exit_1)
def test_vendor_footprint_into_staging(tmp_path, fake_share): # dest_dir + models_dir set → library dirs untouched,
    # model path "${LIB_DIR}/3dmodels/LIB_Package_TO_SOT.3dshapes/…"
@pytest.mark.kicad
def test_upgrade_real(tmp_path): kicad.upgrade("fp", FIX/"C6186/raw/E2K.pretty", tmp_path/"o.pretty") → file starts with "(footprint"
```

- [ ] **Step 2: Run** `py -m pytest tests/test_importer.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement.** Add `easyeda2kicad==1.0.1` to `requirements.txt` and `pyproject.toml`, then run `py -m pip install -r requirements.txt`.
- [ ] **Step 4: Run** `py -m pytest -q`. Expected: all pass. Then run one live smoke test: `py -c "from libkit.importer import fetch_easyeda; ..."` for C6186 into a scratch dir. Expected: a symbol and a footprint are parsed.
- [ ] **Step 5: Commit** `libkit: fetch parts from EasyEDA and upgrade them with kicad-cli`

---

### Task 7: `add` command (dry run, staging, write) ⚑3 ⚑4 ⚑5

**Files:**
- Create: `tools/libkit/add.py`
- Modify: `tools/libkit/__main__.py`, `tools/libkit/parts.py` (`declare_family(root, name)`: a text insertion that keeps comments)
- Test: `tests/test_add.py`

**Interfaces:**
- Consumes: Tasks 1–6, `symgen.build_symbol_lib/load_source_symbols`, `klc.run_klc`, `datasheet.Checker`, `build.build`, `parts.write_category/load_parts/validate`.
- Produces:
  - `@dataclass AddPlan(ref: str, options: dict, category: str, entry: dict, symbol: str | None, files: dict[str, str], new_family: str | None, warnings: list[str], notes: list[str], klc: list[str], created: str)`:
    - `symbol`: the staged unique symbol, as text;
    - `files`: repo-relative destination → file name in the staging dir;
    - `created`: ISO UTC.
  - `prepare(root: Path, ref: str, *, category=None, symbol=None, footprint=None, family=None, fp_name=None, name=None, pin_types=None, resolve=jlc.resolve, fetch=importer.fetch_easyeda, lang=None, klc=True, kicad_share_dir=None) -> AddPlan`. It writes only into `.libkit/add/<REF>/` (REF = `mpn_name(ref.upper())`), as `plan.json` plus the staged files. Steps:
    1. `part = resolve(ref)`.
       - stock 0 → `ValueError` (rule 2); stock < 100 → warning `low stock N`.
       - An existing part with this LCSC, or the target name (any status), → `ValueError` naming it.
    2. Chip passives (`kind_of` set and package in `METRIC`): `passive_entry(kind, part, schema, known_only=False)`, with the base symbol and `LIB_Passives_SMD` footprint, and no import. Passing `--symbol`, `--footprint` or `--category` for a chip passive is a `ValueError`.
    3. Otherwise:
       - Category: `--category`, or `inductors` when `kind_of` is inductor or bead; else `ValueError("--category is required: one of …")`.
       - Entry: inductors and beads → `passive_entry(kind, part, schema, footprint=<resolved footprint>, known_only=False)`. Everything else: name = `--name` or `mpn_name(mpn)`. Value = formatted inductance for inductors, else the MPN. Description = JLC `describe` without a trailing ` ROHS`. Then manufacturer, `lcsc`, `jlc_type`, `datasheet`, `status`, `stock`, `stock_checked`, and the inductor fields.
       - `--symbol` default: `L`/`FerriteBead` for inductors and beads, else `easyeda`. Its forms are:
         - `easyeda` → `normalize_symbol`;
         - `stock:<Lib>:<Name>` → `stock_symbol`;
         - a name in `src/symbols` → derived from it (nothing staged).
         Unique symbols are named exactly like the part.
       - `--footprint` default `easyeda`. Its forms are:
         - `easyeda` → `normalize_footprint` with `--fp-name` (default `mpn_name(easyeda name)`), and the STEP staged as `<fp-name>.step`;
         - `stock:<Lib>:<Name>` → `vendor_footprint` into staging;
         - `LIB_<Family>:<Name>` → an existing footprint (it must exist).
       - `--family` is required for a new footprint. When it is not in the schema, `new_family` is set.
       - If the footprint file already exists in the family, it is reused and nothing is staged (note `reusing existing footprint …`).
    4. `lang(part)` → `datasheet_lang`; `zh` → warning.
    5. KLC (when `klc` and the checker is installed): `run_klc` on the staged footprint, and on a temp `.kicad_sym` from `build_symbol_lib(category, [Part(entry)], sources ∪ staged, schema)`. Issues go into `klc` as strings.
    6. Previews: when `kicad-cli` is found, `sym export svg` and `fp export svg` write into `.libkit/add/<REF>/preview/`.
  - `load_plan(root, ref, options) -> AddPlan`. It refuses (`ValueError`, saying to dry-run again) when there is no plan, the options differ, the plan is older than 24 h, the LCSC or name is now in the library, or a destination file exists with different content.
  - `apply(root: Path, plan: AddPlan) -> list[Path]`, in this order:
    1. declare the family;
    2. copy the staged files;
    3. append the symbol to `src/symbols/<category>.kicad_sym` (header as in `vendor_symbol` when the file is new);
    4. append the entry with `write_category`;
    5. `build`.
    Any exception restores every modified file from its in-memory bytes, deletes every created file and re-raises.
  - `parts.declare_family(root, name)` inserts `  - {name: <name>}` after the last line of the `families:` list in `schema/library.yaml`. It is a no-op when the family is already declared.
  - CLI: `python -m libkit add <C…|MPN> [--category K] [--symbol S] [--footprint F] [--family F] [--fp-name N] [--name N] [--pin-types "EN=input,#4=passive"] [--write]`.
    - The dry run prints: the entry as YAML; files to create or reuse; warnings; notes; KLC issues; preview paths; then the fixed checklist `check: pinout vs datasheet · pad sizes vs land pattern · 3D model alignment`. It ends with `dry run — rerun with --write to add exactly this`.
    - `--write` prints `added <name> to parts/<category>.yaml` plus the files written.

- [ ] **Step 1: Write failing tests** (fakes: `resolve` from fixtures, `fetch` returns the C6186 fixture, `lang` returns `en`, `klc=False` except in the kicad-marked test)

```python
def test_add_chip_inductor(minilib): p = prepare(minilib, "C1046", resolve=..., lang=...)
    # p.entry["name"] == "L_10u_0805_15mA", p.files == {}, p.symbol is None; minilib/parts unchanged (bytes)
def test_add_chip_passive_rejects_overrides(minilib): with pytest.raises(ValueError): prepare(minilib, "C1046", footprint="easyeda", ...)
def test_add_ic_easyeda(minilib): p = prepare(minilib, "C6186", category="ics_power", family="Package_TO_SOT",
                                              fp_name="SOT-223-3_TabPin2", resolve=..., fetch=...)
    # p.entry["name"] == "AMS1117-3.3", p.entry["footprint"] == "LIB_Package_TO_SOT:SOT-223-3_TabPin2"
    # p.files keys == {"footprints/LIB_Package_TO_SOT.pretty/SOT-223-3_TabPin2.kicad_mod", "3dmodels/LIB_Package_TO_SOT.3dshapes/SOT-223-3_TabPin2.step"}
    # p.new_family == "Package_TO_SOT"; "AMS1117-3.3" in p.symbol; "(" not in p.entry["manufacturer"]; warning mentions unknown manufacturer
def test_add_requires_category(minilib): with pytest.raises(ValueError, match="--category"): prepare(minilib, "C6186", ...)
def test_add_refuses_existing(minilib): # Review Focus 2: C1525 in minilib → ValueError naming C_100n_0402_16V_X7R; same for a deprecated name clash
def test_add_refuses_no_stock(minilib): stock 0 → ValueError; stock 50 → warning "low stock 50"
def test_write_applies_plan(minilib): prepare(...) then apply(minilib, load_plan(minilib, "C6186", opts))
    # schema has family Package_TO_SOT and its comments are intact; footprint, step and src/symbols/ics_power.kicad_sym exist;
    # load_parts has AMS1117-3.3; check(minilib, klc=False) has no errors
def test_load_plan_refuses_changed_options_and_age(minilib): ...
def test_apply_rolls_back(minilib, monkeypatch):   # Review Focus 5
    # snapshot bytes of schema/, parts/, src/; monkeypatch build.build to raise; apply → raises
    # every snapshot file byte-identical; no new files under footprints/, 3dmodels/, src/
@pytest.mark.kicad
def test_add_ic_klc_clean_footprint(minilib): prepare(..., klc=True) → no F5.x/F6.3/F9.1 in p.klc
```

- [ ] **Step 2: Run** `py -m pytest tests/test_add.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** `add.py`, `declare_family` and the CLI.
- [ ] **Step 4: Run** `py -m pytest -q`. Expected: all pass.
- [ ] **Step 5: Live dry runs** (nothing is written to the library; `git status` must stay clean apart from `.libkit/`):
  1. `py -m libkit add C1046`. Expected: `L_10u_0805_15mA`, no files.
  2. `py -m libkit add C1015`. Expected: `FB_100R_0805_800mA`.
  3. `py -m libkit add C408412 --footprint easyeda --family Inductor_SMD --fp-name L_Sunlord_MWSA0503S`. Expected: power inductor `MWSA0503S-100MT`, symbol `L`, footprint and STEP staged.
  4. `py -m libkit add AMS1117-3.3 --category ics_power --symbol stock:Regulator_Linear:AMS1117-3.3 --footprint stock:Package_TO_SOT_SMD:SOT-223-3_TabPin2 --family Package_TO_SOT`. Expected: KLC shows nothing beyond the allow-list.
  5. `py -m libkit add C6186 --category ics_power --family Package_TO_SOT --fp-name SOT-223-3_TabPin2`. Expected: the EasyEDA path; KLC shows at most S4.2; there are previews.
  Open the preview SVGs of 4 and 5 and compare them.
- [ ] **Step 6: Commit** `libkit: add command for single parts with staged import`

---

### Task 8: Documentation and memory

**Files:**
- Modify: `CLAUDE.md`, `README.md`, `docs/superpowers/plans/2026-11-01-library-foundation.md` (mark Plan 3 done in the series list), `docs/superpowers/specs/2026-11-01-kicad-library-design.md` (§6.7 single add: the source preference and the orientation decision)
- Memory: `kicad-lib-project.md`

- [ ] **Step 1: `CLAUDE.md`.**
  - Commands: add `find` and `add`.
  - Workflows, **Single add**: `find` (when only a value is given) → `add` dry run → show the user the report and previews → `--write` after their OK → `check` → commit.
  - The source preference (⚑3): stock KiCad first; easyeda with `--fp-name` in KLC form; families named after KiCad stock (`Package_TO_SOT`, `Package_SO`, `Package_DFN_QFN`, `Inductor_SMD`, …).
  - What to do with remaining KLC S4.2/S4.4: `--pin-types`, or an allow-list entry with a reason and the user's OK.
  - Part naming table: add rows for chip inductors, power inductors (MPN) and ferrite beads `FB_<impedance>_<pkg>_<current>`.
  - Move "inductors are single-add only" into the single-add workflow.
- [ ] **Step 2: `README.md`.**
  - easyeda2kicad and `kicad-cli` are needed for `add`.
  - EasyEDA-sourced footprints and 3D models come from the LCSC/EasyEDA library, while vendored ones come from KiCad (CC-BY-SA, as before).
- [ ] **Step 3: Run** `py -m pytest -q; py -m libkit build; py -m libkit check`. Expected: pass, 0 errors.
- [ ] **Step 4: Commit** `doc: single-part add and find workflows`. Update the memory file (Plan 3 done, the decisions taken).

---

### Task 9: Content — missing passives (each add needs the user's OK)

The values from Plan 2 that are still missing:
- resistors: 62k (0402; only 0.1 % parts were picked), 13R and 16R (0402), 11R and 36R (0603);
- capacitors: 680n (0402, ≥16V), and 1.5u, 6.8u and 15u (0603, 0805 and 1206, ≥25V).

- [ ] **Step 1:** Run `py -m libkit find …` for each value and package with the bulk options (1 %; the capacitors at 16V/25V and the default dielectrics). Collect one proposed C-number per value, following the rules (tier, then known manufacturer, then stock, then datasheet), into a single table that says why each one was chosen (e.g. Extended, stock < 1000, a lower voltage being impossible).
- [ ] **Step 2:** Show the user the table. Do nothing further without their OK; values they reject stay missing.
- [ ] **Step 3:** For each approved part: `py -m libkit add C…` (dry run), then `--write`.
- [ ] **Step 4:** Run `py -m libkit check`. Expected: 0 errors.
- [ ] **Step 5: Commit** `parts: single adds for missing E24/E6 values`

## Deferred

- Rotating EasyEDA footprints to KLC orientation, and JLC CPL rotation per footprint (needed only when CPL export exists).
- Variants that share one unique symbol (e.g. `…RGTR`/`…RGTT`): today the second part needs its own symbol name. Add an option when the first such pair comes up.
- Bulk add of inductors (no parametric source; `find` covers single values).

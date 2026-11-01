# Passive Series Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `bulk-add` covers the passive series the Altium library uses beyond 0402–1206 chips: 1210 MLCCs, 2512 resistors including mΩ current-sense shunts, tantalum capacitors (cases A–D) and SMD aluminium electrolytic capacitors (cans 5–10 mm). Each comes as a full series with one voltage per value.

**Architecture:**
- 1210 and 2512 are new package sizes for the existing resistor and capacitor kinds: a `METRIC` table entry, vendored stock footprints, and jlcsearch (which already answers for both sizes).
- Tantalum and electrolytic capacitors are two new kinds in `entries.KINDS`. They use the `C_Polarized` base symbol and KiCad stock footprints.
- jlcsearch has no parametric data for them, so their candidates come from JLC's own keyword search. They are filtered by `type_name` (`Tantalum Capacitors`, `Aluminum Electrolytic Capacitors - SMD`), case or can size, capacitance and stock.
- The pick rules gain one step for these kinds: among usable parts of the best JLC tier, the highest voltage wins ("one voltage per value", user decision 2026-11-01).
- The dry run → table → `--write` flow stays exactly as it is.

**Tech Stack:** Python 3.12, PyYAML, pytest, KiCad 10 stock footprints (`Capacitor_SMD`, `Capacitor_Tantalum_SMD`, `Resistor_SMD`).

**Spec:** `docs/superpowers/specs/2026-11-01-kicad-library-design.md` (§6.4 data model, §6.6 rules, §6.7 bulk add). Plan series: `docs/superpowers/plans/2026-11-01-library-foundation.md` (Plan 6; Plan 5, the JLC export, is deferred).

## Findings that shaped this plan (probed 2026-11-01)

- **jlcsearch** answers `package=2512` (100 hits at 10 mΩ, 67 at 100 Ω) and `package=1210` (100 hits at 10 µF).
- **Tantalum at JLC:** about 2600 records. Brands are `--` (1234, the Kyocera AVX TAJ/TPS/TCJ series; JLC leaves the brand empty), KEMET (1187) and Vishay (210).
  - Packages: `CASE-A-3216-18(mm)`, `CASE-B-3528-21(mm)`, `CASE-C-6032-28(mm)`, `CASE-D-7343-31(mm)`, `CASE-E-…`, plus imperial names (`1206`, `1411`, `2312`, `2917`) used by some makers for the same cases.
  - About 300 have stock ≥ 1000. Only two are Basic: C7171 `TAJA106K016RNJ` (10 µF 16 V, case A) and C16133 `TAJB107K006RNJ` (100 µF 6.3 V, case B).
  - Attributes: `Capacitance`, `Voltage Rating`, `Tolerance`, `Equivalent Series Resistance(ESR)`.
- **Electrolytic at JLC:** type `Aluminum Electrolytic Capacitors - SMD`, packages `SMD,D<d>xL<l>mm` (`D5xL5.4`, `D6.3xL5.4`, `D6.3xL7.7`, `D8xL10.5`, `D10xL10.5` are the common ones; `L5.5`, `L10.2` are variants of the same can).
  - Of 646 with stock ≥ 1000, the known brands are Rubycon 154, Panasonic 83, Lelon 72, Nichicon 71, Würth 4 and Nippon Chemi-Con 3. All are Extended.
  - Attributes: `Capacitance`, `Voltage Rating`, `Tolerance`, `Lifetime`, `Ripple Current`, `Diameter`.
- **KiCad stock footprints** exist for all of these: `CP_EIA-3216-18_Kemet-A`, `CP_EIA-3528-21_Kemet-B`, `CP_EIA-6032-28_Kemet-C`, `CP_EIA-7343-31_Kemet-D`; `CP_Elec_5x5.4`, `CP_Elec_6.3x5.4`, `CP_Elec_6.3x7.7`, `CP_Elec_8x10.5`, `CP_Elec_10x10.5`; `C_1210_3225Metric`, `R_2512_6332Metric`. Pad 1 is `+` on every CP footprint, and pin 1 of `C_Polarized` is `+`.
- **Value names:** `format_value(0.01, "Ω")` gives `10m`, so a 10 mΩ shunt would be named `R_10m_2512_1pct`, next to a possible `R_10M_2512_1pct`. KiCad's symbol search ignores case.

## Decisions for the user to confirm (marked ⚑ in tasks)

1. ⚑ **Names.**
   - Sub-ohm resistors use `mR` for the value and in the name: `R_10mR_2512_1pct`, value `10mR`.
   - Tantalum: `C_10u_CaseA_16V_Ta`, value `10uF`, package `CaseA`, dielectric `Ta`.
   - Electrolytic: `C_100u_D6.3x7.7_25V_Al`, value `100uF`, package `D6.3x7.7`, dielectric `Al`.

   This follows the capacitor pattern `C_<value>_<pkg>_<voltage>_<dielectric>`.
2. ⚑ **One voltage per value**: the best JLC tier first (rule 1), then the highest rated voltage, then stock. A case or can size where no part meets the rules gives a `none` row, as today.
3. ⚑ **Known manufacturers** gain:
   - `KYOCERA AVX`, also matched by an empty or `--` JLC brand when the MPN starts with `TAJ`, `TPS`, `TCJ`, `TLJ` or `F9`;
   - `Rubycon`, `Nichicon`, `Lelon`;
   - `Würth Elektronik` (alias `Wurth Elektronik`);
   - `Nippon Chemi-Con` (alias `NCC(Nippon Chemi-Con)`).

   Panasonic, KEMET and Vishay are already listed.
4. ⚑ **Series and ranges** for the first bulk runs (all values E6, after the user's OK on each table):
   - **Tantalum**, cases A, B, C, D: 1 µF–470 µF, one row per value and case.
   - **Electrolytic**, cans 5×5.4, 6.3×5.4, 6.3×7.7, 8×10.5, 10×10.5: 1 µF–1000 µF, one row per value and can.
   - **1210 MLCC** X7R/X5R: 1 µF–22 µF at ≥ 50 V, then 47 µF and 100 µF at ≥ 10 V.
   - **2512 resistors**: E12 1R–1M at 1%; shunts E6 1 mΩ–100 mΩ at 1% and ≥ 1 W (the new `--min-power`).
5. ⚑ **Footprints** go into `LIB_Passives_SMD` with the chip passives (one SMD-passives library, as spec §6.3 names it), copied unchanged from KiCad stock with their 3D models.

## Global Constraints

- All Global Constraints of Plans 1–4 still hold (UTF-8 + LF, no absolute paths, names never renamed, stock only in YAML, `build` + `check` 0 errors before a commit, tests offline, network only in the dry runs).
- Selection rules (spec §6.6) unchanged: Basic/Preferred before Extended; stock ≥ ~1000 for bulk; known manufacturers only; ceramic dielectric C0G/NP0, X7R, X5R (never Y5V/Z5U), which does not apply to `Ta`/`Al`; English datasheet preferred within a tier. Capacitors below 10 pF are not wanted (user decision).
- Commits: `libkit:` / `lib:` / `parts:` / `doc:` prefix, one short subject, at most two body lines, no Co-Authored-By trailer. Branch `plan6-passive-series`, merged locally after the user's OK. Library content only after the user's OK on each table.
- Commands are PowerShell from `C:\kicad-db`; `py` means `.venv\Scripts\python`.

## Review Focus

1. **Milli versus mega.** `10m`, `10mR` and `0.01` must be 10 mΩ, and `10M` must be 10 MΩ, on the CLI, in YAML and in the keywords. A dry run for `--from 1m` must never produce mega-ohm rows. → Task 1 `test_milli_ohm_names_and_values`.
2. **Package spellings for the same case or can.** `CASE-A-3216-18(mm)` and `1206`-labelled tantalums, or `SMD,D6.3xL5.4mm` and `SMD,D6.3xL5.5mm`, must land on the same LIB footprint, never on a chip-cap footprint. A tantalum labelled `1206` must not be taken for a 1206 MLCC. → Task 3 `test_case_and_can_mapping`.
3. **Polarity.** Pin 1 of `C_Polarized` (`+`) must meet pad 1 (`+`) of every CP footprint. The pin/pad check from Plan 4 must pass, and the KLC findings on the vendored footprints must be reported as they are. → Task 3 `test_polarized_pins_match_pads`.
4. **Records with missing or odd attributes.** `Voltage Rating` `-`, `Capacitance` `100uF±20%` or ESR `-` must make that candidate unusable, with a reason, and must not crash the dry run. → Task 4 `test_odd_records_rejected`.
5. **Highest-voltage choice across tiers.** A Basic 16 V part must beat an Extended 35 V part (rule 1 first); among Extended parts, 35 V beats 16 V. → Task 4 `test_voltage_order_within_tier`.

---

### Task 1: 1210 and 2512 sizes, mΩ values ⚑1 ⚑5

**Files:**
- Modify: `tools/libkit/entries.py` (`METRIC` gains `"1210": "3225"`, `"2512": "6332"`), `tools/libkit/values.py` (Ω values below 1 are formatted with `mR`: `10mR`; `parse_value` accepts `10mR`, `10m`), `tools/libkit/__main__.py` (`--package` choices gain `1210`, `2512`)
- Vendor: `py -m libkit vendor-fp Capacitor_SMD:C_1210_3225Metric --family Passives_SMD`; `Resistor_SMD:R_2512_6332Metric`
- Test: `tests/test_values.py`, `tests/test_entries.py`

- [ ] **Step 1: Write failing tests**

```python
def test_milli_ohm_names_and_values():  # Review Focus 1
    assert format_value(0.01, "Ω") == "10mR" and parse_value("10mR", "Ω") == parse_value("10m", "Ω") == 0.01
    assert parse_value("10M", "Ω") == 1e7
    assert passive_name("resistor", 0.01, "2512", tolerance=0.01) == "R_10mR_2512_1pct"
def test_metric_1210_2512(): assert footprint_for("capacitor", "1210") == "LIB_Passives_SMD:C_1210_3225Metric" and footprint_for("resistor", "2512") == "LIB_Passives_SMD:R_2512_6332Metric"
def test_existing_names_unchanged(minilib): # every existing resistor/capacitor name rebuilds identically (no value >= 1R changes notation)
```

- [ ] **Step 2: Run** `py -m pytest tests/test_values.py tests/test_entries.py -v`. Expected: the new tests FAIL.
- [ ] **Step 3: Implement**; vendor the two footprints (KLC: report findings; allow-list only stock-unchanged findings, as before).
- [ ] **Step 4: Run** `py -m pytest -q`; `py -m libkit build; py -m libkit check`. Expected: all pass, 0 errors, no generated symbol changed (`git diff --stat symbols/` empty).
- [ ] **Step 5: Commit** `libkit: 1210 and 2512 sizes, mR notation below 1 ohm`

---

### Task 2: Minimum power for resistor picks

**Files:**
- Modify: `tools/libkit/pick.py` (`Need.min_power: float | None`), `tools/libkit/bulk.py` (`_mismatch` checks `power`), `tools/libkit/__main__.py` (`bulk-add` / `find`: `--min-power 1W`, kept in the plan options)
- Test: `tests/test_pick.py`, `tests/test_bulk.py`

- [ ] **Step 1: Write failing tests**: `test_min_power_filters_candidates` (a 0.5 W candidate is rejected for `min_power=1`, with the reason "power 500mW"); `test_plan_options_include_min_power` (a plan made without `--min-power` is refused by `--write --min-power 1W`).
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement.** `_mismatch` parses `power` (`1W`, `500mW`, `1/4W`); an unparseable power fails the need when `min_power` is set.
- [ ] **Step 4: Run** `py -m pytest -q`. Expected: all pass.
- [ ] **Step 5: Commit** `libkit: minimum power for resistor picks`

---

### Task 3: Tantalum and electrolytic kinds ⚑1 ⚑3 ⚑5

**Files:**
- Modify: `tools/libkit/entries.py`, `schema/library.yaml` (manufacturers; capacitors gain optional `{key: esr, label: ESR}` and `{key: lifetime, label: Lifetime}`)
- Create: `tools/libkit/polar.py`
- Vendor: the four `Capacitor_Tantalum_SMD:CP_EIA-…_Kemet-[ABCD]` and five `Capacitor_SMD:CP_Elec_…` footprints into `Passives_SMD`
- Create fixtures: `tests/fixtures/jlc/` records for C7171, C16133, one KEMET T491 (case C), one `1206`-labelled AVX tantalum, one Rubycon and one Panasonic electrolytic (6.3×7.7 and 8×10.5), and one record with `Voltage Rating` `-`
- Test: `tests/test_polar.py`, `tests/test_entries.py`

**Interfaces:**
- Produces:
  - `KINDS` gains `"tantalum": ("capacitors", "C_Polarized", "F", "CP")` and `"electrolytic": ("capacitors", "C_Polarized", "F", "CP")`.
  - `polar.CASES = {"A": ("3216-18", "CP_EIA-3216-18_Kemet-A"), "B": ("3528-21", …), "C": ("6032-28", …), "D": ("7343-31", …)}`; `polar.CANS = {"5x5.4": "CP_Elec_5x5.4", "6.3x5.4": …, "6.3x7.7": …, "8x10.5": …, "10x10.5": …}`.
  - `polar.case_of(part: JlcPart) -> str | None`: `CASE-<X>-…` → X. An imperial package (`1206`, `1411`, `2312`, `2917`) counts only when `type_name` is `Tantalum Capacitors`; it is then mapped by EIA size (1206→A, 1411→B, 2312→C, 2917→D).
  - `polar.can_of(part) -> str | None`: `SMD,D<d>xL<l>mm` → the key in `CANS` with the same `d` and `|l − key l| ≤ 0.3`.
  - `entries.passive_entry` for these kinds:
    - name per ⚑1; `value` `10uF`; `package` `CaseA` or `D6.3x7.7`; `voltage`; `dielectric` `Ta` or `Al`; `tolerance`; `esr` / `lifetime` when JLC has them;
    - footprint `LIB_Passives_SMD:<CASES/CANS footprint>`;
    - description from the template, e.g. `10uF 16V Ta ±10% CaseA capacitor`.
  - `schema.canonical_manufacturer(brand, mpn="")` gains the MPN-prefix rule for an empty or `--` brand (⚑3); callers pass the MPN.

- [ ] **Step 1: Record fixtures** (network, once).
- [ ] **Step 2: Write failing tests**

```python
def test_case_and_can_mapping():  # Review Focus 2
    assert case_of(rec_part("C7171")) == "A" and case_of(<1206-labelled AVX>) == "A"
    assert can_of(<D6.3xL7.7>) == "6.3x7.7" and can_of(<D6.3xL5.5>) == "6.3x5.4" and can_of(<1206 MLCC record>) is None
def test_tantalum_entry(): e = passive_entry("tantalum", rec_part("C7171"), schema); assert e["name"] == "C_10u_CaseA_16V_Ta" and e["symbol"] == "C_Polarized" and e["manufacturer"] == "KYOCERA AVX"
def test_electrolytic_entry(): # Rubycon 6.3x7.7 -> "C_<v>_D6.3x7.7_<V>_Al", footprint CP_Elec_6.3x7.7
def test_polarized_pins_match_pads(minilib): # build a tantalum + an electrolytic part; check(klc=False) has no pin/pad issue  (Review Focus 3)
def test_unknown_brand_without_prefix_stays_unknown(): # brand "--", MPN "XYZ123" -> canonical None
```

- [ ] **Step 3: Run** `py -m pytest tests/test_polar.py tests/test_entries.py -v`. Expected: FAIL.
- [ ] **Step 4: Implement**; vendor the footprints; report their KLC findings to the user (allow-list only after their OK).
- [ ] **Step 5: Run** `py -m pytest -q`; `py -m libkit build; py -m libkit check`. Expected: all pass, 0 errors.
- [ ] **Step 6: Commit** `libkit: tantalum and electrolytic capacitor kinds`

---

### Task 4: Bulk add for tantalum and electrolytic ⚑2 ⚑4

**Files:**
- Modify: `tools/libkit/polar.py` (candidate source), `tools/libkit/pick.py` (voltage order), `tools/libkit/bulk.py`, `tools/libkit/__main__.py`
- Test: `tests/test_polar.py`, `tests/test_bulk.py`

**Interfaces:**
- Produces:
  - `polar.candidates(kind, value: float, size: str, post=None) -> list[JlcPart]`: JLC keyword search `"<value> <size keyword>"` (`"10uF 3216"` / `"100uF 6.3x7.7"`), 2 pages. It keeps records whose `type_name` is right for the kind, whose `case_of`/`can_of` equals `size`, and whose `Capacitance` equals `value` within 1%.
  - `pick.pick_polar(need, parts: list[JlcPart], schema, check, lang) -> Pick`: rules 1–3 and 6 as in `pick`. Among usable parts, the order is: tier, then highest `voltage`, then English datasheet, then stock (⚑2). A part whose `voltage` cannot be parsed is rejected, with a reason.
  - CLI: `bulk-add tantalum --series E6 --from 1u --to 470u --case A` and `bulk-add electrolytic --series E6 --from 1u --to 1000u --can 6.3x7.7`. Plan file: `.libkit/bulk-plan-<kind>-<case|can>.json`. `--tolerance` / `--voltage` are optional for these kinds (no filter by default).
  - Table: the `type` column as today, plus `voltage`.

- [ ] **Step 1: Write failing tests**

```python
def test_voltage_order_within_tier():  # Review Focus 5
    # Basic 16V vs Extended 35V -> Basic 16V; two Extended (16V, 35V) -> 35V
def test_odd_records_rejected():  # Review Focus 4
    # Voltage Rating "-" / Capacitance "100uF±20%" -> rejected with reason; another candidate wins
def test_plan_tantalum_rows(minilib): # fake search: two values, one with no usable part -> rows new/none, names per ⚑1
def test_write_tantalum_plan(minilib): # save + load_plan + apply -> parts/capacitors.yaml has the rows, build ok, check(klc=False) 0 errors
def test_cli_case_required(): # bulk-add tantalum without --case -> error naming A, B, C, D
```

- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `py -m pytest -q`. Expected: all pass.
- [ ] **Step 5: Commit** `libkit: bulk add for tantalum and electrolytic capacitors`

---

### Task 5: Docs, dry runs, review

- [ ] **Step 1: Docs.** In `CLAUDE.md`:
  - commands (`--case`, `--can`, `--min-power`);
  - the naming table (sub-ohm `mR`, tantalum, electrolytic);
  - a bulk-add workflow note: one voltage per value; `mR` vs `M`.

  Spec §6.4: a "Decided (Plan 6)" paragraph. Plan series: Plan 6 done. Commit `doc: passive series`.
- [ ] **Step 2: Final review** of the whole branch by one fresh reviewer; fixes in `libkit: final review fixes`; ask the user before merging.
- [ ] **Step 3: Dry runs (network)** for every series in ⚑4. Show the user every table; `--write` only the approved ones (`--skip` for the rest); `build`, `check`, commit `parts: …` per series.

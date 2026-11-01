# JLC Data, Bulk Add and Stock Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Claude can look up any LCSC part, bulk-add resistors and capacitors by value series with automatic part picks by the spec's rules, and refresh stock for the whole library — all through `python -m libkit`.

**Architecture:** Two public, keyless JSON sources. jlcsearch.tscircuit.com gives *parametric candidates* for resistors and capacitors (value, package, tolerance, voltage, dielectric, stock, Basic/Preferred). JLC's own parts-search endpoint gives the *authoritative record* for one C-number (brand, MPN, stock, library type, LCSC datasheet URL, attributes). Picking runs as pure functions over normalised records, so it is tested offline with recorded responses. YAML is written only after the whole run succeeds.

**Tech Stack:** Python 3.12 stdlib `urllib` + PyYAML (already present), pytest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-11-01-kicad-library-design.md` (§6.6 selection rules, §6.7 bulk add / stock refresh / data source)

## Findings that shaped this plan (probed 2026-11-01)

- `POST https://jlcpcb.com/api/overseas-pcb-order/v1/shoppingCart/smtGood/selectSmtComponentList` with body `{"keyword": "C25744", "currentPage": 1, "pageSize": 5}` works without login. In `data.componentPageInfo.list[]` it returns:
  - `componentCode` ("C25744"), `componentModelEn` (MPN), `componentBrandEn` ("UNI-ROYAL(Uniroyal Elec)"), `componentSpecificationEn` ("0402");
  - `stockCount`, `componentLibraryType` ("base" = Basic, "expand" = Extended), `preferredComponentFlag`;
  - `dataManualUrl` (a stable direct LCSC PDF), `describe`, `attributes[]` (`attribute_name_en` / `attribute_value_name`).
- `GET https://jlcsearch.tscircuit.com/resistors/list.json?package=0402&resistance=10000` and `/capacitors/list.json?package=0402&capacitance=1e-7`:
  - return up to 100 candidates, sorted by stock, with `lcsc` (int), `mfr`, `stock` (may be null), `is_basic`, `is_preferred`, `tolerance_fraction`, `power_watts` (in mW despite the name), `voltage_rating`, `temperature_coefficient` (dielectric), `capacitance_farads`;
  - include no manufacturer name, so the brand comes from JLC;
  - have no inductor endpoint (404), so inductors stay single-add for now.
- The Basic 10 pF parts are **C0G**. The user therefore changed rule 4 (2026-11-01) to allow C0G/NP0 alongside X7R/X5R.

## Global Constraints

- Everything from Plan 1's Global Constraints still holds (UTF-8 + LF, no absolute paths, names never renamed, stock never in symbols, `build` + `check` clean before commit).
- Selection rules (spec §6.6), verbatim:
  1. JLC **Basic or Preferred** before Extended; Extended only if nothing fits.
  2. Stock: **≥ ~1000 for bulk-added passives**. For single parts I name myself: any stock > 0 is accepted, with a warning below ~100.
  3. **Known manufacturers only** (list in repo, e.g. Samsung, Murata, Yageo, UNI-ROYAL, TDK, …; extendable).
  4. Ceramic capacitors: **C0G/NP0, X7R or X5R**, never Y5V/Z5U (C0G/NP0 added 2026-11-01: JLC's Basic small values are C0G, the better dielectric there).
  5. Bulk adds show the full list for confirmation before anything is written.
- The network is used only by `jlc`, `bulk-add` and `refresh-stock`. `build`, `check` and the test suite stay offline (live tests are opt-in with `LIBKIT_LIVE=1`).
- At most 4 requests per second; 20 s timeout; `User-Agent: libkit/0.2 (personal KiCad library)`.
- Any network or format error aborts the command **before** a single YAML file is written.
- Datasheet field = JLC's `dataManualUrl` (direct LCSC PDF). This replaces Plan 1's `https://www.lcsc.com/datasheet/<C>.pdf` convention for new parts.

## Review Focus

1. **Brand strings** from JLC ("UNI-ROYAL(Uniroyal Elec)", "Samsung Electro-Mechanics", "FH(Guangdong Fenghua Advanced Tech)") must map to the canonical manufacturer names, and unknown brands must be rejected for bulk picks. → Task 1 `test_brand_canonical`.
2. **Float value matching**: `capacitance_farads` 1.0000000000000001e-7 must match 100 nF, and 4.7 kΩ must not match 47 kΩ. → Task 2 `test_value_match_tolerance`.
3. **Re-running a bulk add** must skip values whose name already exists, and must skip a picked LCSC number already in the library; never a duplicate. → Task 4 `test_bulk_skips_existing`.
4. **API failure mid-run** (timeout, HTTP 500, missing field) must write nothing and exit 1 with the C-number or value that failed. → Task 4 `test_bulk_aborts_without_writing`, Task 5 `test_refresh_aborts_without_writing`.
5. **YAML rewrite** must keep `"0402"`, `±`, `µ`, `°C` and every untouched part byte-identical in meaning (load before == load after, plus the new entries). → Task 3 `test_write_roundtrip_preserves_parts`.

---

### Task 1: HTTP layer, JLC lookup and manufacturer aliases

**Files:**
- Create: `tools/libkit/net.py`, `tools/libkit/jlc.py`
- Modify: `schema/library.yaml` (manufacturers become `{name, aliases}`), `tools/libkit/schema.py`, `tools/libkit/parts.py` (validate against canonical names), `tools/libkit/__main__.py` (`jlc` command)
- Create fixtures: `tests/fixtures/jlc/C1525.json`, `C25744.json`, `C32949.json` (raw recorded responses), `notfound.json`
- Test: `tests/test_jlc.py`

**Interfaces:**
- Produces:
  - `net.get_json(url: str) -> dict` and `net.post_json(url: str, body: dict) -> dict`. Both raise `net.NetError(str)` on timeout, a non-2xx status or invalid JSON. They are rate-limited to 4 requests per second, process-wide.
  - `@dataclass JlcPart(lcsc: str, mpn: str, brand: str, package: str, stock: int, jlc_type: str, datasheet: str, description: str, attributes: dict[str, str])`
    - `lcsc` looks like `"C1525"`.
    - `jlc_type` is `"Basic" | "Preferred" | "Extended"`.
  - `jlc.lookup(lcsc: str, post=net.post_json) -> JlcPart | None` — matches `componentCode` exactly; `None` when the part isn't listed; raises `NetError` when the response has the wrong shape.
  - `jlc.parse_record(rec: dict) -> JlcPart`
  - `Schema.manufacturers: list[Manufacturer]`, with `@dataclass Manufacturer(name: str, aliases: list[str])`.
  - `Schema.canonical_manufacturer(brand: str) -> str | None` — case-insensitive match when the brand equals the name or an alias, or starts with the name followed by a space or `(`.
  - CLI: `python -m libkit jlc C1525` prints the normalised record as `key: value` lines, followed by `canonical manufacturer: Samsung` (or `unknown`).

`jlc_type` mapping: `"Preferred"` if `preferredComponentFlag`, else `"Basic"` if `componentLibraryType == "base"`, else `"Extended"`.

Manufacturers in `schema/library.yaml` (`aliases` only where the prefix rule doesn't cover it): Samsung [Samsung Electro-Mechanics], Murata, Yageo, UNI-ROYAL, TDK, Vishay, KEMET, Panasonic, Taiyo Yuden, Walsin, FH, Sunlord.

- [ ] **Step 1: Record fixtures.** Run the JLC POST for C1525, C25744, C32949 and a nonsense code (`C999999999`). Save the raw JSON pretty-printed (UTF-8) into `tests/fixtures/jlc/`.
- [ ] **Step 2: Write failing tests**

```python
def test_parse_record_basic(): p = parse_record(rec("C25744"))
    # p.lcsc == "C25744", p.mpn == "0402WGF1002TCE", p.package == "0402", p.jlc_type == "Basic"
    # p.datasheet.startswith("https://www.lcsc.com/datasheet/"), p.attributes["Resistance"] == "10kΩ", p.stock > 0
def test_lookup_exact_match_only(): assert lookup("C1525", post=fake("C1525.json")).mpn == "CL05B104KO5NNNC"
def test_lookup_not_found(): assert lookup("C999999999", post=fake("notfound.json")) is None
def test_lookup_bad_shape_raises(): with pytest.raises(NetError): lookup("C1", post=lambda u, b: {"code": 200})
@pytest.mark.parametrize("brand,name", [("Samsung Electro-Mechanics","Samsung"), ("UNI-ROYAL(Uniroyal Elec)","UNI-ROYAL"),
    ("FH(Guangdong Fenghua Advanced Tech)","FH"), ("YAGEO","Yageo"), ("TAIYO YUDEN","Taiyo Yuden"), ("Murata Electronics","Murata")])
def test_brand_canonical(schema, brand, name): assert schema.canonical_manufacturer(brand) == name   # Review Focus 1
def test_brand_unknown(schema): assert schema.canonical_manufacturer("Fenghuaxyz Ltd") is None and schema.canonical_manufacturer("FHX") is None
def test_validate_still_warns_unknown_passive_manufacturer(): ...  # existing test keeps passing with the new schema shape
@pytest.mark.skipif(os.environ.get("LIBKIT_LIVE") != "1", reason="live network test")
def test_live_lookup(): assert lookup("C1525").brand.startswith("Samsung")
```

- [ ] **Step 3: Run** `py -m pytest tests/test_jlc.py -v` — Expected: FAIL (ImportError).
- [ ] **Step 4: Implement** `net.py`, `jlc.py`, the schema changes and the `jlc` CLI.
- [ ] **Step 5: Run** `py -m pytest -q`, then `$env:LIBKIT_LIVE=1; py -m pytest tests/test_jlc.py -q; Remove-Item Env:LIBKIT_LIVE`, then `py -m libkit jlc C1525`.
  Expected: all pass; the live test passes; the CLI prints `jlc_type: Basic` and `canonical manufacturer: Samsung`.
- [ ] **Step 6: Commit** `feat: JLC part lookup and manufacturer aliases`

---

### Task 2: Candidates and the picker

**Files:**
- Create: `tools/libkit/jlcsearch.py`, `tools/libkit/pick.py`
- Create fixtures: `tests/fixtures/jlcsearch/res_0402_10000.json`, `cap_0402_1e-07.json`, `cap_0402_1e-11.json` (raw recorded)
- Test: `tests/test_pick.py`

**Interfaces:**
- Consumes: `JlcPart`, `jlc.lookup`, `Schema.canonical_manufacturer`, `values.parse_value`.
- Produces:
  - `@dataclass Candidate(lcsc: str, mpn: str, package: str, value: float, tolerance: float | None, voltage: float | None, power_mw: float | None, dielectric: str | None, stock: int, jlc_type: str)`
    - `tolerance` is a fraction; `voltage` is in V.
  - `jlcsearch.resistors(package: str, ohms: float, get=net.get_json) -> list[Candidate]`
  - `jlcsearch.capacitors(package: str, farads: float, get=net.get_json) -> list[Candidate]`
    - Candidates whose value differs by more than 0.5 % from the request are dropped.
  - `@dataclass Need(kind: str, value: float, package: str, max_tolerance: float, min_voltage: float | None = None, dielectrics: tuple[str, ...] = ("C0G", "NP0", "X7R", "X5R"), min_stock: int = 1000)`
    - `kind` is `"resistor"` or `"capacitor"`.
  - `@dataclass Pick(need: Need, part: JlcPart | None, candidate: Candidate | None, note: str)`
  - `pick(need: Need, candidates: list[Candidate], schema: Schema, lookup=jlc.lookup) -> Pick`

Picking algorithm (the spec rules decide the order):
1. Filter by: tolerance ≤ `max_tolerance`; voltage ≥ `min_voltage` (capacitors); dielectric in `dielectrics` (capacitors); stock ≥ `min_stock`.
2. Sort: Basic/Preferred first, then stock descending.
3. Walk the sorted list and `lookup()` each LCSC number. Take the first one whose brand canonicalises to a known manufacturer and whose JLC stock still meets `min_stock`. Stop after 8 lookups.
4. With no pick, `note` names the first failing reason that emptied the list, e.g. `"no candidate with dielectric C0G/NP0/X7R/X5R"`, `"no known manufacturer among 8 checked"`. Otherwise `note` is `""`, or `"Extended part"` when the pick is Extended.

- [ ] **Step 1: Record fixtures** with the three GET URLs above.
- [ ] **Step 2: Write failing tests**

```python
def test_candidates_parsed(): c = resistors("0402", 10000, get=fake("res_0402_10000.json"))[0]
    # c.lcsc == "C25744", c.tolerance == 0.01, c.power_mw == 62.5, c.jlc_type == "Basic"
def test_value_match_tolerance():   # Review Focus 2
    assert all(abs(c.value - 1e-7) / 1e-7 < 0.005 for c in capacitors("0402", 1e-7, get=fake("cap_0402_1e-07.json")))
    assert capacitors("0402", 1e-6, get=fake("cap_0402_1e-07.json")) == []     # 100n response never satisfies 1u
def test_pick_prefers_basic(schema): p = pick(Need("capacitor", 1e-7, "0402", 0.1, 16), caps, schema, lookup=fake_lookup)
    # p.part.lcsc == "C1525", p.part.jlc_type == "Basic", p.note == ""
def test_pick_respects_min_voltage(schema): ... Need(..., min_voltage=50) → picked candidate.voltage >= 50
def test_pick_rejects_y5v(schema): candidates all Y5V/Z5U → pick(...).part is None and "dielectric" in note
def test_pick_c0g_by_default(schema): pick(Need("capacitor", 1e-11, "0402", 0.05, 50), caps10p, ...).part.lcsc == "C32949"
def test_pick_skips_unknown_brand(schema): lookup returning brand "NoName" for the first → second candidate chosen
def test_pick_extended_noted(schema): only Extended candidates → p.note == "Extended part"
def test_pick_stock_threshold(schema): all stock < 1000 → p.part is None and "stock" in p.note
```

`fake_lookup` builds a `JlcPart` from `tests/fixtures/jlc/` when a fixture exists, otherwise from the candidate (brand given per test).

- [ ] **Step 3: Run** `py -m pytest tests/test_pick.py -v` — Expected: FAIL.
- [ ] **Step 4: Implement** `jlcsearch.py` and `pick.py`.
- [ ] **Step 5: Run** `py -m pytest -q` — Expected: all pass.
- [ ] **Step 6: Commit** `feat: JLC candidates and rule-based part picker`

---

### Task 3: Series, part entries and YAML writing

**Files:**
- Create: `tools/libkit/series.py`, `tools/libkit/entries.py`
- Modify: `tools/libkit/parts.py` (add `write_category`)
- Test: `tests/test_entries.py`

**Interfaces:**
- Consumes: `JlcPart`, `Need`, `values.format_value`, `Schema`.
- Produces:
  - `series.values(name: str, start: float, stop: float) -> list[float]`
    - `name` is one of `E6 E12 E24 E48 E96`; inclusive range; standard EIA tables (E48/E96 at 3 significant digits).
  - `entries.passive_name(kind: str, value: float, package: str, *, tolerance: float | None = None, voltage: float | None = None, dielectric: str | None = None) -> str` — the CLAUDE.md patterns: `R_10k_0402_1pct`, `C_100n_0402_16V_X7R`.
  - `entries.footprint_for(kind: str, package: str) -> str` — `LIB_Passives_SMD:<R|C>_<pkg>_<metric>Metric` for 0402/0603/0805/1206; `ValueError` otherwise.
  - `entries.passive_entry(kind: str, part: JlcPart, schema: Schema) -> dict[str, str]` — the full YAML entry:
    - `status: active`, `stock` = JLC stock, `stock_checked` = today in ISO format;
    - `manufacturer` = canonical name;
    - category fields taken from the JLC attributes: Tolerance, Power(Watts), Temperature Coefficient (with `℃` normalised to `°C`); Voltage Rating, Temperature Coefficient → dielectric.
  - `parts.write_category(root: Path, category: str, entries: list[dict]) -> None` — rewrites `parts/<category>.yaml` as `parts:` plus entries in schema field order (common fields, then category fields). Every value is written as a string; YAML adds quotes where needed. UTF-8, LF, `allow_unicode`. Atomic: write to `.tmp`, then replace.

- [ ] **Step 1: Write failing tests**

```python
def test_e12_decade(): assert series.values("E12", 1000, 10000) == [1000,1200,1500,1800,2200,2700,3300,3900,4700,5600,6800,8200,10000]
def test_e96_count(): assert len(series.values("E96", 100, 999)) == 96
def test_unknown_series(): with pytest.raises(ValueError): series.values("E7", 1, 10)
def test_names():
    assert passive_name("resistor", 4700, "0603", tolerance=0.01) == "R_4.7k_0603_1pct"
    assert passive_name("capacitor", 1e-7, "0402", voltage=16, dielectric="X7R") == "C_100n_0402_16V_X7R"
    assert passive_name("capacitor", 4.7e-6, "0805", voltage=6.3, dielectric="X5R") == "C_4.7u_0805_6.3V_X5R"
def test_footprint_for(): assert footprint_for("capacitor", "0603") == "LIB_Passives_SMD:C_0603_1608Metric"
def test_passive_entry_from_jlc(schema):   # from fixture C25744
    e = passive_entry("resistor", parse_record(rec("C25744")), schema)
    # e["manufacturer"] == "UNI-ROYAL", e["value"] == "10k", e["tolerance"] == "±1%", e["power"] == "62.5mW",
    # e["tempco"] == "±100ppm/°C", e["name"] == "R_10k_0402_1pct", validate([...]) has no errors
def test_write_roundtrip_preserves_parts(minilib, schema):   # Review Focus 5
    before = load_parts(minilib, schema)
    write_category(minilib, "capacitors", [p.data for p in before if p.category == "capacitors"] + [new_entry])
    after = load_parts(minilib, schema)
    # every old part's data is equal; the new one is present; "0402" is still "0402";
    # "±10%" is intact; the file has no "\r\n"
```

`new_entry` is built from the C1525 fixture.

- [ ] **Step 2: Run** `py -m pytest tests/test_entries.py -v` — Expected: FAIL.
- [ ] **Step 3: Implement** `series.py`, `entries.py`, `write_category`.
- [ ] **Step 4: Run** `py -m pytest -q` — Expected: all pass.
- [ ] **Step 5: Commit** `feat: value series, passive entries and YAML writer`

---

### Task 4: `bulk-add` command

**Files:**
- Create: `tools/libkit/bulk.py`
- Modify: `tools/libkit/__main__.py`
- Test: `tests/test_bulk.py`

**Interfaces:**
- Consumes: everything from Tasks 1–3.
- Produces:
  - `bulk.plan(root: Path, kind: str, series_name: str, start: float, stop: float, package: str, max_tolerance: float, min_voltage: float | None, dielectrics: tuple[str, ...], get=..., lookup=...) -> list[Row]`
  - `@dataclass Row(value: str, name: str, status: str, entry: dict | None, note: str)`
    - `status` is `"new" | "exists" | "none"`.
    - `"exists"` covers both a name already in the library and a picked LCSC number already in the library.
  - `bulk.apply(root: Path, kind: str, rows: list[Row]) -> int` — writes all `"new"` rows in one `write_category` call and returns how many it wrote.
  - CLI:
    ```
    python -m libkit bulk-add resistor  --series E24 --from 1k  --to 1M  --package 0402 --tolerance 1%
    python -m libkit bulk-add capacitor --series E6  --from 1n  --to 1u  --package 0402 --tolerance 10% --voltage 16V [--dielectric C0G,NP0,X7R,X5R] [--write]
    ```
    - Values are parsed with `parse_value`.
    - It always prints a table: value · name · status · LCSC · MPN · manufacturer · type · stock · note.
    - Without `--write` it writes nothing and ends with `dry run: N new, M existing, K without a part — rerun with --write to add`.
    - With `--write`, the plan is recomputed and applied, then `build` runs. Exit 0.
    - Any `NetError` → exit 1, nothing written.

- [ ] **Step 1: Write failing tests** (fake `get`/`lookup` built from the recorded fixtures)

```python
def test_bulk_plan_rows(minilib): rows = plan(minilib, "capacitor", "E6", 1e-7, 1e-7, "0402", 0.1, 16, ("X7R","X5R"), get=..., lookup=...)
    # [r.status for r in rows] == ["exists"]   (fixture already has C_100n_0402_16V_X7R)
def test_bulk_skips_existing(minilib):  # Review Focus 3
    # the picked LCSC equals one already in parts/ under a different name → status "exists", note mentions that name
def test_bulk_none_reported(minilib): # no candidates → status "none" with note; not dropped
def test_bulk_apply_writes_and_builds(minilib): n = apply(...); assert n == 1 and new name in load_parts(...) and errors(minilib) == []
def test_bulk_aborts_without_writing(minilib):  # Review Focus 4
    before = (minilib/"parts"/"capacitors.yaml").read_bytes()
    with pytest.raises(NetError): plan(..., lookup=raises_on_second_call)
    assert (minilib/"parts"/"capacitors.yaml").read_bytes() == before
def test_cli_dry_run_writes_nothing(minilib, monkeypatch): ... "dry run:" in output, file unchanged
```

For CLI tests, `bulk.plan`'s network defaults are swapped via `monkeypatch.setattr(net, "get_json", ...)` / `net.post_json`.

- [ ] **Step 2: Run** `py -m pytest tests/test_bulk.py -v` — Expected: FAIL.
- [ ] **Step 3: Implement** `bulk.py` and the CLI.
- [ ] **Step 4: Run** `py -m pytest -q` — Expected: all pass.
- [ ] **Step 5: Live dry run** (no `--write`): `py -m libkit bulk-add resistor --series E12 --from 1k --to 10k --package 0402 --tolerance 1%`.
  Expected: 13 rows; `10k` shows `exists`; most rows Basic with stock > 1000; the exit code is 0; `git status` is clean.
- [ ] **Step 6: Commit** `feat: bulk-add command for resistors and capacitors`

---

### Task 5: `refresh-stock` command

**Files:**
- Create: `tools/libkit/stock.py`
- Modify: `tools/libkit/__main__.py`
- Test: `tests/test_stock.py`

**Interfaces:**
- Produces:
  - `stock.refresh(root: Path, lookup=jlc.lookup, today: date | None = None) -> list[Change]`
    - Updates `stock`, `stock_checked` and `jlc_type` of every part with an `lcsc` field, in memory, then writes each changed category file.
    - Raises `NetError` before writing anything if any lookup fails.
  - `@dataclass Change(part: str, kind: str, detail: str)`
    - `kind` is one of `"not_found"`, `"out_of_stock"`, `"low_stock"`, `"type_changed"`, `"mpn_changed"`.
    - `low_stock` means < 1000 for categories with a `value_unit` (passives), < 100 otherwise.
  - CLI: `python -m libkit refresh-stock` prints the changes, one per line, and `refreshed N parts`; runs `build` when any `jlc_type` changed; exit 0.

- [ ] **Step 1: Write failing tests**

```python
def test_refresh_updates_stock_and_date(minilib): refresh(minilib, lookup=fake, today=date(2026,11,2)) → C1525 stock == fixture stockCount, stock_checked "2026-11-02"
def test_refresh_reports(minilib): fake returning None → Change(kind="not_found"); stock 0 → "out_of_stock"; Basic→Extended → "type_changed"
def test_refresh_low_stock_thresholds(minilib): passive with 500 → low_stock; an ics_power part with 500 → nothing
def test_refresh_aborts_without_writing(minilib):  # Review Focus 4
    bytes before == bytes after when lookup raises NetError on the 2nd part
```

- [ ] **Step 2: Run** `py -m pytest tests/test_stock.py -v` — Expected: FAIL.
- [ ] **Step 3: Implement** `stock.py` and the CLI.
- [ ] **Step 4: Run** `py -m pytest -q` — Expected: pass.
- [ ] **Step 5: Live**
  1. Run `py -m libkit refresh-stock`. Expected: the 2 parts get stock and today's date; no `type_changed`.
  2. Run `py -m libkit build; py -m libkit check`. Expected: 0 errors.
  3. `git diff parts/`. Expected: only the stock lines and dates changed.
- [ ] **Step 6: Commit** `feat: refresh-stock command` (includes the refreshed stock in `parts/`)

---

### Task 6: Documentation

**Files:**
- Modify: `CLAUDE.md`, `README.md`

- [ ] **Step 1: `CLAUDE.md`.** Add a "Workflows" section:
  - **Single lookup:** `jlc C…`.
  - **Bulk add:** always run the dry run first, show the user the table, and run `--write` only after their OK.
  - **Stock refresh:** `refresh-stock`.
  - Change the datasheet rule to "JLC's `dataManualUrl`; `bulk-add` fills it in".
  - Keep rule 4 as already updated in CLAUDE.md (C0G/NP0, X7R, X5R; never Y5V/Z5U).
- [ ] **Step 2: `README.md`.** Add one paragraph naming the two data sources and noting that they are unofficial, keyless APIs that may change.
- [ ] **Step 3: Run** `py -m pytest -q; py -m libkit check` — Expected: pass, 0 errors.
- [ ] **Step 4: Commit** `docs: bulk-add and stock workflows`

## Resolved question

C0G/NP0 dielectric: allowed (user, 2026-11-01). Rule 4 now reads "C0G/NP0, X7R or X5R; never Y5V/Z5U" in the spec, CLAUDE.md and this plan; `Need.dielectrics` defaults to all four names.

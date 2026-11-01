# Review GUI, Discrete Base Symbols and Local Parts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `libkit build` also writes a read-only review page (`build/review/index.html`, spec §6.9, layout A); diodes, LEDs and small transistors derive from shared base symbols like R/C/L, and `libkit add` picks those bases by itself where the JLC record allows it; non-orderable parts (mounting holes, test points, fiducials) can be added without a C-number.

**Architecture:** A new module `review.py` turns the parts, the schema and the preview SVGs into `build/review/data.js` (`window.LIB_DATA = …`). It copies a static page (`review_page.html`: HTML, CSS and JS in one file) next to it, so the page works from `file://` with no server and no network. `kicad-cli` renders previews per generated symbol library and per footprint library, cached by content hash. `libkit check` writes its results to `build/review/check.js` (`window.LIB_CHECK = …`), stamped with a hash of the part data, so the page can tell current results from stale ones. A new module `pins.py` compares symbol pins with footprint pads; `check` and `add` use it. A new module `discretes.py` classifies a JLC record (`componentTypeEn` + attributes) into category, default base symbol, required pads and category fields.

**Tech Stack:** Python 3.12, PyYAML, pytest, KiCad 10.0.1 `kicad-cli` (`sym export svg`, `fp export svg`), plain HTML/CSS/JS (no libraries, no build step).

**Spec:** `docs/superpowers/specs/2026-11-01-kicad-library-design.md` (§6.9 review GUI, §6.5 symbols, §6.2 categories, §6.8 checks). Plan series: `docs/superpowers/plans/2026-11-01-library-foundation.md` (this is Plan 4).

## Findings that shaped this plan (probed 2026-11-01)

- `kicad-cli sym export svg <lib.kicad_sym> -o <dir>` renders every symbol of a library, derived symbols included and with their own Value text, as `<name>_unit<N>.svg` (~9 KB each; 139 capacitors in 0.4 s). `kicad-cli fp export svg <dir.pretty> -o <dir>` writes `<footprint>.svg` (~18 KB) but **fails when `<dir>` does not exist**: create it first.
- JLC records carry `componentTypeEn`, which libkit does not read yet: `Switching Diodes` (1N4148W, C81598), `Schottky Diodes` (SS34, C8678), `Zener Diodes` (ZMM3V3-M, C8056), `LED Indication - Discrete` (KT-0603R, C2286), `MOSFETs` (AO3400A C20917, AO3401A C15127, IRFPE50PBF C2932 in TO-247), `Bipolar (BJT)` (MMBT3904, C20526), `ESD and Surge Protection (TVS/ESD)` (SM712, C7420375: 2 channels).
- Polarity is spelled inconsistently: AO3400A `Type: N-Channel`, `Number: 1 N-channel`; AO3401A `Type: -`, `Number: 1 P-Channel`; MMBT3904 `type: NPN`, `Number: 1 NPN`. Diode configuration: `Standalone`, `1 Independent`, `Discrete Diode` (LED). TVS: `Polarity: Bidirectional`, `Number of Channels: 2`.
- KiCad stock bases and pin numbers: `Device:D`, `D_Schottky`, `D_Zener`, `LED` = K/1, A/2; `Device:D_TVS` = A1/1, A2/2 (bidirectional only; KiCad has no unidirectional TVS base). `Device:Q_NMOS`/`Q_NPN` use pin numbers `D G S` / `B C E`, which match no footprint. The SOT-23 pinout bases are `Transistor_FET:Q_NMOS_GSD`, `Q_PMOS_GSD` (G1 S2 D3) and `Transistor_BJT:Q_NPN_BEC`, `Q_PNP_BEC` (B1 E2 C3); KiCad's own 2N7002/BSS138/MMBT3904 derive from them.
- Mechanical bases: `Mechanical:MountingHole`, `MountingHole_Pad`, `Fiducial`; `Connector:TestPoint`. Stock footprint libraries `MountingHole`, `TestPoint`, `Fiducial`.
- `refresh-stock` already skips parts without `lcsc`. Node.js is not installed: the page's JS is checked in a browser (Task 9), Python tests check the data and the static page.

## Interpretation of the request and decisions for the user (marked ⚑ in tasks)

1. ⚑ **Page = one HTML file plus side files.** `build/review/index.html` is the page; next to it `data.js`, `check.js` and `svg/…` (all under gitignored `build/`). Separate files instead of one inlined HTML file keep the page small when there are hundreds of IC previews; `<script src>` and `<img src>` work from `file://`, `fetch()` would not and is not used.
2. ⚑ **Check results come from `libkit check`**, not from `build` (KLC takes minutes over the whole library). `build` puts only the fast results into the page (schema warnings, pin/pad check); the page marks `check.js` stale when the part data changed since.
3. ⚑ **New check: symbol pins vs. footprint pads.** A symbol pin without a pad of that number is an error; a numbered footprint pad without a pin is a warning. Applies to every part, existing ones included (all R/C pass: pins 1, 2 ↔ pads 1, 2).
4. ⚑ **Discrete base symbols** in `src/symbols/discretes.kicad_sym`, copied unchanged from KiCad stock: `D`, `D_Schottky`, `D_Zener`, `D_TVS`, `LED`, `Q_NMOS_GSD`, `Q_PMOS_GSD`, `Q_NPN_BEC`, `Q_PNP_BEC`. Mechanical bases in `src/symbols/mechanical.kicad_sym`: `MountingHole`, `MountingHole_Pad`, `Fiducial`, `TestPoint`.
5. ⚑ **`add` defaults to a base only when it can tell**: a single diode/LED whose footprint has exactly pads {1, 2}; a single N/P MOSFET or NPN/PNP BJT in a SOT-23-family package whose footprint has exactly pads {1, 2, 3}. Otherwise (dual diodes, unidirectional TVS, TO-252, …) it keeps the EasyEDA symbol and says why in a note. The category is defaulted from `componentTypeEn` either way, so `--category` becomes optional for these parts. Names stay the MPN, value stays the MPN.
6. ⚑ **New category fields**: diodes `vz` (Vz); LEDs `color` (Color), `vf` (Vf). `add` fills diode, LED and transistor fields from JLC attributes.
7. ⚑ **Local parts**: `libkit add <name> --local --category mechanical --footprint stock:<Lib>:<Name> --family <Family> [--symbol …] [--value …] [--description …]`. No network, refused for orderable categories, symbol defaulted from the footprint library (MountingHole → `MountingHole` or `MountingHole_Pad` for `*_Pad`; Fiducial → `Fiducial`; TestPoint → `TestPoint`), `package` = footprint name, `value` = name unless given, `description` = the footprint's `descr` unless given. Footprint families follow KiCad stock (`MountingHole`, `TestPoint`, `Fiducial`), per CLAUDE.md, instead of one `Mechanical` family.
8. ⚑ **KLC allow-list**: new stock bases get allow-list entries only for findings on unchanged stock content, each listed for the user's OK in Task 2.

## Global Constraints

- All Global Constraints of Plans 1–3 still hold: UTF-8 + LF (`write_text`), no absolute paths, names never renamed or reused, `stock`/`stock_checked` never written into symbols, `build` + `check` with 0 errors before a commit, network only in `jlc`, `bulk-add` (dry run), `refresh-stock`, `find` and `add` (dry run, not `--local`).
- Spec §6.9 verbatim: "A **single static HTML page** generated by the build into `build/`, opened by double-click; no server. Search box over all fields, category filter chips, column chooser. Table: name, value, package, key params, manufacturer, MPN, LCSC, JLC type (colour tag), stock (warning colours). Detail panel on row click: symbol + footprint preview (SVG rendered with `kicad-cli`), all fields, check results, links: datasheet, JLC/LCSC page, copy MPN. Read-only."
- Offline: the page loads nothing over the network (no CDN, no web fonts, no `fetch`); only outbound links the user clicks (datasheet, LCSC, JLC).
- Nothing new is committed from `build/` or `.libkit/` (both gitignored already).
- `build` works without `kicad-cli` (a friend's clone): the page then has no previews and says so. Tests never run `kicad-cli` except those marked `@pytest.mark.kicad`; `tests/conftest.py` sets `LIBKIT_PREVIEWS=0` for all tests (autouse), and preview tests enable rendering explicitly.
- Stock colours use the thresholds of `stock.py`: `LOW_STOCK_PASSIVE` (1000) for categories with a `value_unit`, `LOW_STOCK_OTHER` (100) otherwise; 0 = out of stock.
- Links: LCSC `https://www.lcsc.com/product-detail/<LCSC>.html`, JLC `https://jlcpcb.com/parts/componentSearch?searchTxt=<LCSC>`, datasheet = the part's `datasheet`.
- Commits: `libkit:` / `lib:` / `parts:` / `doc:` / `treewide:` prefix, one short subject, at most two body lines, **no Co-Authored-By trailer**. Branch `plan4-review-gui`, merged locally after the user's OK. Library content only after the user's OK on each add.
- Commands are PowerShell from `C:\kicad-db`; `py` means `.venv\Scripts\python`.

## Review Focus

1. **Part text that looks like markup.** A description with `</script>`, `<img onerror=…>` or quotes must show as text in table and detail panel and must not end the `data.js` script. → Task 6 `test_data_js_escapes_markup`; the page builds every cell with `textContent`, never `innerHTML` with data (Task 9 browser check).
2. **`kicad-cli` missing or failing on one library.** `build` still succeeds; parts of that library show "no preview" instead of a broken image; the page lists the failure. → Task 7 `test_build_without_cli`, `test_render_failure_is_a_note`.
3. **Stale or missing check results.** Page opened before any `check`, or after a build that changed parts: it must say "not checked" / "results are older than the data", not show old results as current. → Task 8 `test_check_js_hash_matches_data`, `test_check_js_stale_after_change`.
4. **A base symbol whose pin numbers fit the pads but not the pinout.** A MOSFET in TO-252 (pads 1, 2, 3 but G, D, S) must not get `Q_NMOS_GSD`; a dual diode in SOT-23 must not get `D`. → Task 3 `test_transistor_default_only_sot23`, Task 4 `test_add_dual_diode_keeps_easyeda`.
5. **Local parts in the wrong place.** `--local` in an orderable category, with `--footprint easyeda`, or with a taken name must be refused; `refresh-stock` must leave local parts alone. → Task 5 `test_local_refuses_orderable_category`, `test_local_refuses_easyeda`, `test_local_refuses_existing_name`, `test_refresh_skips_local_parts`.

---

### Task 1: Symbol pins vs. footprint pads ⚑3

**Files:**
- Create: `tools/libkit/pins.py`
- Modify: `tools/libkit/check.py` (call after the footprint-exists checks)
- Test: `tests/test_pins.py`

**Interfaces:**
- Produces:
  - `symbol_pins(name: str, sources: dict[str, list]) -> set[str]`: pin numbers of source symbol `name`, following `extends` through `sources`, over all units; `KeyError` for an unknown name.
  - `footprint_pads(path: Path) -> set[str]`: non-empty pad numbers of a `.kicad_mod`.
  - `pin_pad_issues(parts: list[Part], sources: dict[str, list], root: Path) -> list[Issue]`: per part whose symbol and footprint both exist: `error` "symbol pin(s) 3, 4 have no pad in <fp>"; `warning` "footprint pad(s) MP have no symbol pin". Footprint pads are parsed once per footprint.

- [ ] **Step 1: Write failing tests**

```python
def test_symbol_pins_passive(minilib): assert symbol_pins("R", load_source_symbols(minilib)) == {"1", "2"}
def test_symbol_pins_follows_extends(): # sources {"Base": <2 pins>, "Child": (extends "Base")} -> {"1","2"}
def test_footprint_pads_ignores_unnumbered(tmp_path): # pads "1", "2", "" -> {"1","2"}
def test_pin_without_pad_is_error(minilib): # part with symbol R on a 1-pad footprint -> 1 error naming pin "2"
def test_extra_pad_is_warning(minilib):     # 3-pad footprint (1,2,MP) -> 1 warning naming "MP", no error
def test_check_clean_on_minilib(minilib): assert not [i for i in check(minilib, klc=False) if "pin" in i.message]
```

- [ ] **Step 2: Run** `py -m pytest tests/test_pins.py -v`. Expected: FAIL (ImportError).
- [ ] **Step 3: Implement** `pins.py` and call `pin_pad_issues` from `check()` when sources loaded without error.
- [ ] **Step 4: Run** `py -m pytest -q` and `py -m libkit check --no-klc`. Expected: all pass; check 0 errors, no pin warnings on the real library.
- [ ] **Step 5: Commit** `libkit: check symbol pins against footprint pads`

---

### Task 2: Discrete and mechanical base symbols, new fields ⚑4 ⚑6 ⚑8

**Files:**
- Create (via `vendor-sym`): `src/symbols/discretes.kicad_sym`, `src/symbols/mechanical.kicad_sym`
- Modify: `schema/library.yaml` (diodes `vz`; leds_optoelectronics `color`, `vf`), `schema/klc-allowlist.yaml` (⚑ only with the user's OK)
- Test: `tests/test_build.py`

- [ ] **Step 1: Vendor the bases** (one command each):
  `py -m libkit vendor-sym Device:D --into discretes`, likewise `Device:D_Schottky`, `Device:D_Zener`, `Device:D_TVS`, `Device:LED`, `Transistor_FET:Q_NMOS_GSD`, `Transistor_FET:Q_PMOS_GSD`, `Transistor_BJT:Q_NPN_BEC`, `Transistor_BJT:Q_PNP_BEC`; `Mechanical:MountingHole`, `Mechanical:MountingHole_Pad`, `Mechanical:Fiducial`, `Connector:TestPoint` `--into mechanical`.
  Expected: `grep -c '^\t(symbol "' src/symbols/discretes.kicad_sym` = 9 (no parents pulled in; if a base `extends` something, its parent is listed too: report it).
- [ ] **Step 2: Schema fields.** diodes gain `{key: vz, label: Vz}`; `leds_optoelectronics` becomes a mapping with `fields: [{key: color, label: Color, keyword: true}, {key: vf, label: Vf}]`.
- [ ] **Step 3: Write failing test**

```python
def test_discrete_part_derives_from_base(minilib):
    # copy REPO src/symbols/discretes.kicad_sym; add a diodes.yaml part {symbol: D, value: 1N4148W, vr: 75V, ...,
    # footprint on a 2-pad fixture footprint}; build -> symbols/LIB_Diodes.kicad_sym has (symbol "D" ...) and
    # (symbol "1N4148W" (extends "D") ...) with property "Vr" "75V"
```

- [ ] **Step 4: Run** `py -m pytest tests/test_build.py -v`. Expected: PASS once the fixture part and the copied symbol file are in place (no code change expected; if it fails, fix symgen and say why).
- [ ] **Step 5: KLC on the new bases.** Build a scratch library holding one derived part per base (as `add._klc` does) and run `run_klc` on it. Report every finding to the user with the proposed allow-list entry (extend the `&stock_bases` list for S3.3/S3.6/S4.1-type findings on unchanged stock content). Add entries only after their OK.
- [ ] **Step 6: Run** `py -m libkit build; py -m libkit check`. Expected: 0 errors (bases are unused, so generated libraries do not change).
- [ ] **Step 7: Commit** `lib: discrete and mechanical base symbols, diode and LED fields`

---

### Task 3: Classify discretes from the JLC record ⚑5 ⚑6

**Files:**
- Modify: `tools/libkit/jlc.py` (`JlcPart.type_name: str = ""` as the **last** field, from `componentTypeEn`)
- Create: `tools/libkit/discretes.py`
- Create fixtures: `tests/fixtures/jlc/C81598.json`, `C8678.json`, `C8056.json`, `C2286.json`, `C20917.json`, `C15127.json`, `C20526.json`, `C2932.json`, `C7420375.json`, plus one dual diode (e.g. BAT54S) and one single bidirectional TVS (e.g. an SMAJ…CA); find their C-numbers with `py -m libkit find`-style search or `py -m libkit jlc`.
- Test: `tests/test_discretes.py`

**Interfaces:**
- Produces:
  - `@dataclass Discrete: category: str; symbol: str | None; pads: frozenset[str]; fields: dict[str, str]; checklist: str; why: str = ""` (`why`: reason when `symbol` is None).
  - `classify(part: JlcPart) -> Discrete | None`. `None` when `type_name` is none of the kinds below. Rules, in order (type and attribute names compared case-folded, whitespace removed, `"-"` = missing, via `entries._attr`):

| `type_name` contains | single when | base | pads | category | fields |
|---|---|---|---|---|---|
| `LED` | `Diode Configuration` missing or `Discrete Diode`, colour without `/` or `RGB` | `LED` | 1, 2 | leds_optoelectronics | color ← `Illumination Color`, vf ← `Voltage - Forward(Vf)` |
| `TVS` or `ESD` | `Number of Channels` missing or `1`, `Polarity` = `Bidirectional` | `D_TVS` | 1, 2 | diodes | vr ← `Reverse Stand-Off Voltage (Vrwm)` |
| `Zener` | configuration single¹ | `D_Zener` | 1, 2 | diodes | vz ← `Zener Voltage(Nom)` |
| `Schottky` | configuration single¹ | `D_Schottky` | 1, 2 | diodes | vr, if ← `Current - Rectified`, vf ← `Voltage - Forward(Vf@If)` |
| `Diode` (not `Bridge`) | configuration single¹ | `D` | 1, 2 | diodes | vr ← `Voltage - DC Reverse(Vr)`, if, vf |
| `MOSFET` | `Number` starts with `1 ` or is missing; polarity N/P from `Type` or `Number` (`n-channel` / `p-channel`); package in `SOT23_FAMILY` | `Q_NMOS_GSD` / `Q_PMOS_GSD` | 1, 2, 3 | transistors | type `N-MOSFET`/`P-MOSFET`, v_max ← `Drain to Source Voltage`, i_max ← `Current - Continuous Drain(Id)`, rds_on ← `RDS(on)` |
| `BJT` | as MOSFET; polarity `NPN`/`PNP` from `type` or `Number` | `Q_NPN_BEC` / `Q_PNP_BEC` | 1, 2, 3 | transistors | type, v_max ← `Collector - Emitter Voltage VCEO`, i_max ← `Current - Collector(Ic)` |

  ¹ `Diode Configuration` missing, `Standalone`, `Single`, `1 Independent`. When the row matches but "single" or the package fails, return the category and fields with `symbol=None` and `why` (e.g. "2 channels", "package TO-247AC-3 is not SOT-23-like").
  - `SOT23_FAMILY = {"SOT-23", "SOT-23-3", "SOT-23-3L", "SOT-323", "SOT-323-3", "SC-70", "SC-70-3", "SOT-416", "SOT-523"}`.
  - `checklist`: diodes/LEDs `"pad 1 = cathode (K), pad 2 = anode (A)"` (`D_TVS`: `"bidirectional: pad order free"`); MOSFETs `"pads 1/2/3 = G/S/D"`; BJTs `"pads 1/2/3 = B/E/C"`.

- [ ] **Step 1: Record fixtures** with live POSTs, saved like the existing ones (pretty-printed UTF-8).
- [ ] **Step 2: Write failing tests**

```python
@pytest.mark.parametrize("code, symbol, category", [("C81598","D","diodes"), ("C8678","D_Schottky","diodes"),
    ("C8056","D_Zener","diodes"), ("C2286","LED","leds_optoelectronics"), ("C20917","Q_NMOS_GSD","transistors"),
    ("C15127","Q_PMOS_GSD","transistors"), ("C20526","Q_NPN_BEC","transistors")])
def test_classify(code, symbol, category): d = classify(parse_record(rec(code))); assert (d.symbol, d.category) == (symbol, category)
def test_transistor_default_only_sot23(): d = classify(parse_record(rec("C2932"))); assert d.symbol is None and d.category == "transistors" and "TO-247" in d.why  # Review Focus 4
def test_multi_channel_tvs_no_default(): assert classify(parse_record(rec("C7420375"))).symbol is None
def test_dual_diode_no_default(): assert classify(parse_record(rec("<BAT54S>"))).symbol is None
def test_fields(): assert classify(parse_record(rec("C20917"))).fields == {"type": "N-MOSFET", "v_max": "30V", "i_max": "5.7A", "rds_on": "48mΩ@2.5V"}
def test_led_fields(): assert classify(parse_record(rec("C2286"))).fields == {"color": "Red", "vf": "1.8V~2.4V"}
def test_not_discrete(): assert classify(parse_record(rec("C6186"))) is None and kind_of(parse_record(rec("C81598"))) is None
def test_type_name_parsed(): assert parse_record(rec("C8678")).type_name == "Schottky Diodes"
```

- [ ] **Step 3: Run** `py -m pytest tests/test_discretes.py -v`. Expected: FAIL (ImportError).
- [ ] **Step 4: Implement** `type_name` and `discretes.py`; `py -m libkit jlc` prints `type_name` with the other fields (it uses `asdict`).
- [ ] **Step 5: Run** `py -m pytest -q`. Expected: all pass.
- [ ] **Step 6: Commit** `libkit: classify diodes, LEDs and transistors from JLC records`

---

### Task 4: `add` defaults to discrete base symbols ⚑5

**Files:**
- Modify: `tools/libkit/add.py` (`prepare`, `_entry`)
- Test: `tests/test_add.py` (the `lib` fixture also copies `src/symbols/discretes.kicad_sym`; fixture footprints: KiCad stock `Diode_SMD:D_SOD-123` and `Package_TO_SOT_SMD:SOT-23` via `kicad_share_dir` pointing at a test share folder with those two files, or the real share for `@pytest.mark.kicad` tests)

**Interfaces:**
- Consumes: `discretes.classify`, `pins.footprint_pads`, `pins.symbol_pins`.
- Produces (behaviour of `prepare` for non-chip parts):
  - `category` defaults to `KINDS[kind][0]`, else `classify(part).category`.
  - With no `--symbol` and `disc.symbol` set: the footprint is resolved first; its pads (staged or existing file) are compared with `disc.pads`. Equal → `entry["symbol"] = disc.symbol`, note `"base symbol <S>; check: <checklist>"`. Not equal → EasyEDA symbol (fetched now if not fetched yet), note `"base <S> does not fit pads <sorted pads>: EasyEDA symbol"`. `disc.symbol is None` → EasyEDA symbol, note `"no base symbol: <why>"`.
  - `entry` gains `disc.fields` for keys the category declares.
  - Every non-chip add runs the pin/pad comparison of its final symbol (base or staged unique) against its footprint; pins without pads → `ValueError("… would fail check: symbol pin(s) … have no pad in …")`.

- [ ] **Step 1: Write failing tests**

```python
def test_add_diode_uses_base(lib): # C81598, footprint stock:Diode_SMD:D_SOD-123, family Diode_SMD, no --category
    # plan.category == "diodes", entry["symbol"] == "D", plan.symbol is None, entry["vr"] == "75V", "cathode" in notes
def test_add_mosfet_uses_base(lib): # C20917 + stock SOT-23 -> "Q_NMOS_GSD", entry["type"] == "N-MOSFET"
def test_add_dual_diode_keeps_easyeda(lib): # <BAT54S> -> plan.symbol is not None, a note starting "no base symbol"  (Review Focus 4)
def test_add_base_pad_mismatch_falls_back(lib): # C81598 on a 3-pad footprint -> EasyEDA symbol, note "does not fit pads 1, 2, 3"
def test_add_explicit_symbol_wins(lib): # C81598 --symbol D_Schottky -> entry["symbol"] == "D_Schottky"
def test_add_refuses_pin_without_pad(lib): # --symbol Q_NMOS_GSD on D_SOD-123 -> ValueError "pin(s) 3"
def test_write_diode_builds_and_checks(lib): # dry run + apply -> symbols/LIB_Diodes.kicad_sym has extends "D"; check(klc=False) 0 errors
```

- [ ] **Step 2: Run** `py -m pytest tests/test_add.py -v`. Expected: the new tests FAIL.
- [ ] **Step 3: Implement** in `prepare`; keep the order "footprint, then symbol" and fetch EasyEDA lazily (only when the footprint or the final symbol needs it).
- [ ] **Step 4: Run** `py -m pytest -q`. Expected: all pass (older add tests unchanged).
- [ ] **Step 5: Commit** `libkit: add picks discrete base symbols where the record allows`

---

### Task 5: Local (non-orderable) parts ⚑7

**Files:**
- Modify: `tools/libkit/add.py` (`prepare_local`), `tools/libkit/__main__.py` (`--local`, `--value`, `--description`)
- Test: `tests/test_add.py`, `tests/test_stock.py`

**Interfaces:**
- Produces:
  - `prepare_local(root: Path, name: str, *, category: str, footprint: str, family: str | None = None, symbol: str | None = None, value: str | None = None, description: str | None = None, klc: bool = True, previews: bool = False, kicad_share_dir: Path | None = None) -> AddPlan` — same staging, `plan.json`, KLC and previews as `prepare`; `ref` = `name`; `options` include `local=True`, `value`, `description`. Uses `_footprint` (stock or existing `LIB_<Family>:<Name>`; `easyeda` → `ValueError("--local parts have no C-number: use a stock: or LIB_ footprint")`).
  - `local_symbol(footprint_ref: str) -> str | None`: `MountingHole:*_Pad*` → `MountingHole_Pad`, `MountingHole:*` → `MountingHole`, `Fiducial:*` → `Fiducial`, `TestPoint:*` → `TestPoint`, else `None` (then `--symbol` is required).
  - Entry: `name, symbol, footprint, value (= value or name), package (= footprint name), description (= description or the footprint's descr; ValueError when both are empty), status: active`.
  - CLI: `add <ref> --local …` calls `prepare_local`; `--write` works unchanged via `load_plan`/`apply`; `--value`/`--description` without `--local` → `ValueError`.

- [ ] **Step 1: Write failing tests**

```python
def test_local_mounting_hole(lib): # prepare_local("MountingHole_3.2mm_M3", category="mechanical",
    # footprint="stock:MountingHole:MountingHole_3.2mm_M3", family="MountingHole", kicad_share_dir=<share with that file>)
    # entry == {name, symbol: "MountingHole", footprint: "LIB_MountingHole:MountingHole_3.2mm_M3", value: name,
    #           package: "MountingHole_3.2mm_M3", description: <stock descr>, status: "active"}; plan.new_family == "MountingHole"
def test_local_write_and_check(lib): # apply -> symbols/LIB_Mechanical.kicad_sym extends "MountingHole"; check(klc=False) 0 errors
def test_local_refuses_orderable_category(lib): # category="diodes" -> ValueError "non-orderable"   (Review Focus 5)
def test_local_refuses_easyeda(lib):            # footprint="easyeda" -> ValueError "no C-number"
def test_local_refuses_existing_name(lib):      # second prepare_local after apply -> ValueError "already in the library"
def test_local_needs_symbol_for_unknown_fp(lib): # footprint of another stock lib, no --symbol -> ValueError "--symbol"
def test_cli_local_dry_run_and_write(lib, monkeypatch, capsys): # main(["add", name, "--local", ...]) then with --write
# tests/test_stock.py
def test_refresh_skips_local_parts(minilib): # a mechanical part without lcsc; fake lookup asserts it is never asked
```

- [ ] **Step 2: Run** `py -m pytest tests/test_add.py tests/test_stock.py -v`. Expected: the new tests FAIL.
- [ ] **Step 3: Implement** `prepare_local`, `local_symbol` and the CLI flags.
- [ ] **Step 4: Run** `py -m pytest -q`. Expected: all pass.
- [ ] **Step 5: Commit** `libkit: add non-orderable parts with --local`

---

### Task 6: Review data and page ⚑1

**Files:**
- Create: `tools/libkit/review.py`, `tools/libkit/review_page.html`
- Modify: `tools/libkit/build.py` (`build()` calls `write_review(root)` after writing the generated files), `tools/libkit/__main__.py` (`_build` prints `review page: build/review/index.html`), `pyproject.toml` (`[tool.setuptools.package-data] libkit = ["*.html"]`), `tests/conftest.py` (autouse `monkeypatch.setenv("LIBKIT_PREVIEWS", "0")`)
- Test: `tests/test_review.py`

**Interfaces:**
- Produces:
  - `REVIEW_DIR = Path("build") / "review"`.
  - `library_hash(root: Path) -> str`: sha256 hex of the canonical JSON of `[(p.category, p.data) for p in load_parts(...)]`, sorted by name.
  - `review_data(root: Path, svg_dir: Path | None = None, notes: list[str] | None = None) -> dict` with keys `hash`, `built` (ISO local time), `notes`, `previews` (bool), `categories` (`[{key, title, lib, count}]`, only categories with parts), `parts`. Each part: `name, category, lib, value, package, params` (`[[label, value]]` of the category's own fields that are set, schema order), `manufacturer, mpn, lcsc, jlc_type, stock` (int or `None`), `stock_low` (threshold per Global Constraints), `stock_checked, datasheet, datasheet_lang, status, description` (`build_description`), `footprint, symbol, keywords` (`build_keywords`), `fields` (`[[label or key, value]]` for every set field, schema order), `issues` (`[{severity, message}]` from `validate` + `pin_pad_issues` for this part), `sym_svgs` (list of paths relative to `build/review/`, `unit` order), `fp_svg` (path or `None`).
  - `write_review(root: Path, *, previews: bool | None = None, run=subprocess.run) -> Path`: writes `data.js` (`window.LIB_DATA = <json>;\n`, `ensure_ascii=True`, every `<` written as `\u003c`) and copies `review_page.html` to `index.html`; returns the index path. `previews=None` means: on unless `LIBKIT_PREVIEWS == "0"` or no `kicad-cli` (Task 7 fills in the rendering; until then previews are off).

- **Page (`review_page.html`, inline CSS + JS, system fonts, light and dark via `prefers-color-scheme`):**
  - Loads `<script src="data.js">` and `<script src="check.js">`; missing `check.js` is not an error.
  - Header: "LIB parts", "N of M parts", build time, check status pill (Task 8), any `notes`.
  - Search box (focused on load, `/` focuses it): whitespace-separated terms, case-insensitive, every term must occur in the part's haystack (all `fields` values, `keywords`, category title, footprint, symbol).
  - Category chips with counts; toggles, none selected = all.
  - Column chooser (button + checkbox list). Default columns: Name, Value, Package, Params, Manufacturer, MPN, LCSC, JLC, Stock. Optional: Category, Description, Footprint, Status, Datasheet lang, Stock checked. Choice saved in `localStorage`, every access in `try/catch`.
  - Table: click a header to sort (Stock numeric, others text); JLC type as a coloured tag (Basic green, Preferred blue, Extended amber); stock cell red at 0, amber below `stock_low`, `—` when `None`; deprecated rows muted with a `deprecated` tag; a ●/▲ marker when the part has errors/warnings.
  - Detail panel (right; below the table under 900 px width) on row click, also selected by URL hash `#<name>`: name, description, tags; symbol SVG(s) and footprint SVG on a white card (or "no preview"); all fields as a label/value list plus keywords; check results (build-time `issues` + `check.js`); links Datasheet (with `datasheet_lang`), LCSC, JLC (`target="_blank" rel="noopener"`, absent without `lcsc`); buttons "Copy MPN" and "Copy LCSC" (`navigator.clipboard.writeText`, fallback hidden textarea + `document.execCommand("copy")`).
  - Every data value goes into the DOM through `textContent` / attributes; no `innerHTML` with data.

- [ ] **Step 1: Write failing tests**

```python
def test_review_data_parts(minilib): # every minilib part present; a resistor has params [["Tolerance","1%"],["Power",…]], stock int, stock_low 1000
def test_review_data_categories(minilib): # only categories with parts, counts match
def test_build_writes_page(minilib): build(minilib); assert (minilib/"build/review/index.html").exists() and (minilib/"build/review/data.js").read_text().startswith("window.LIB_DATA = ")
def test_data_js_escapes_markup(minilib): # description "</script><img src=x onerror=alert(1)>" -> data.js has no "</script>" and no "<img"; json round-trip restores it  (Review Focus 1)
def test_page_is_offline(): # review_page.html has no (src|href)="http…", no "@import", no "fetch(", no "innerHTML ="
def test_library_hash_changes_with_data(minilib): # editing one field changes the hash; rebuilding without changes keeps it
def test_deprecated_part_included(minilib): # status deprecated -> present with status "deprecated" and empty keywords
```

- [ ] **Step 2: Run** `py -m pytest tests/test_review.py -v`. Expected: FAIL (ImportError).
- [ ] **Step 3: Implement** `review.py`, the page, the build hook and the conftest env.
- [ ] **Step 4: Run** `py -m pytest -q`; `py -m libkit build`; `git status --short`. Expected: all pass; build prints the page path; `git status` shows no files under `build/`.
- [ ] **Step 5: Commit** `libkit: review page generated by build`

---

### Task 7: Symbol and footprint previews

**Files:**
- Modify: `tools/libkit/review.py`
- Test: `tests/test_review.py`

**Interfaces:**
- Produces:
  - `render_previews(root: Path, svg_dir: Path, run=subprocess.run) -> list[str]` (notes): for each `symbols/<Lib>.kicad_sym` → `svg_dir/sym/<Lib>/` via `kicad-cli sym export svg <file> -o <dir>`; for each `footprints/<Lib>.pretty` → `svg_dir/fp/<Lib>/` via `kicad-cli fp export svg <dir> -o <dir>` (create `<dir>` first). Skips a library whose sha256 (file, or the sorted `.kicad_mod` files of the folder) equals `<dir>/.src-hash`; otherwise empties `<dir>`, renders, writes `.src-hash` only on success. Non-zero exit → note `"preview of <Lib> failed: <last stderr line>"`, the library keeps no SVGs. Removes `<dir>`s whose library no longer exists.
  - `write_review` with previews on: `svg_dir = build/review/svg`; `review_data` maps `sym_svgs` to existing `sym/<Lib>/<name>_unit<N>.svg` (sorted by N) and `fp_svg` to `fp/<FpLib>/<fp>.svg`; previews off → note `"previews off: kicad-cli not found"` (or `"… LIBKIT_PREVIEWS=0"`), both lists empty.

- [ ] **Step 1: Write failing tests**

```python
def test_previews_cached(minilib): # fake run that writes the expected svg names and counts calls: second write_review(previews=True) -> no new calls; editing parts/resistors.yaml + build -> only LIB_Resistors re-rendered
def test_render_failure_is_a_note(minilib): # fake run returncode 1 for LIB_Capacitors -> note names it, capacitors have sym_svgs == [], others filled  (Review Focus 2)
def test_build_without_cli(minilib, monkeypatch): # find_kicad_cli -> None, LIBKIT_PREVIEWS unset: build succeeds, data previews False, note "kicad-cli not found"  (Review Focus 2)
@pytest.mark.kicad
def test_render_real(minilib): # write_review(previews=True) with real kicad-cli -> R part has sym_svgs ["svg/sym/LIB_Resistors/<name>_unit1.svg"], fp_svg exists on disk
```

- [ ] **Step 2: Run** `py -m pytest tests/test_review.py -v`. Expected: the new tests FAIL.
- [ ] **Step 3: Implement** `render_previews` and its use in `write_review`.
- [ ] **Step 4: Run** `py -m pytest -q`; `py -m libkit build` twice (the second is fast: no renders). Expected: all pass; `build/review/svg/sym/LIB_Resistors/` holds 481 SVGs.
- [ ] **Step 5: Commit** `libkit: symbol and footprint previews on the review page`

---

### Task 8: Check results on the page ⚑2

**Files:**
- Modify: `tools/libkit/review.py`, `tools/libkit/__main__.py` (`_check` writes the results), `tools/libkit/review_page.html` (status pill, per-part results)
- Test: `tests/test_review.py`

**Interfaces:**
- Produces:
  - `assign_issues(issues: list[Issue], root: Path) -> tuple[dict[str, list[dict]], list[dict]]`: `(per part name, library-wide)`. `Issue.part` matching rules, in order: a part name; `<Lib>:<Name>` with `Name` a part name; `<Lib>:<Base>` (or `Base`) with `Base` a base symbol → every part in `<Lib>` (or anywhere) whose `symbol` is `Base`; a footprint name or `<FpLib>:<Name>` → every part using that footprint; else library-wide (also `part is None`).
  - `write_check_results(root: Path, issues: list[Issue], *, klc: bool) -> Path`: writes `build/review/check.js` = `window.LIB_CHECK = {"hash", "time", "klc", "errors", "warnings", "parts", "library"};` (same escaping as `data.js`); `hash` = `library_hash(root)`, or `""` when the parts do not load.
  - Page: pill "check ✓ 0 errors · KLC · <time>" (green), "check: N errors" (red), "not checked" (grey, no `check.js`), "check results are older than the data" (grey, hash differs; per-part results then shown with a "stale" label).

- [ ] **Step 1: Write failing tests**

```python
def test_assign_by_symbol_item(minilib): # Issue("error", "LIB_Resistors:R_10k_0402_1pct", "KLC S3.3 …") -> parts["R_10k_0402_1pct"]
def test_assign_base_symbol_to_users(minilib): # "LIB_Resistors:R" -> every resistor, no capacitor
def test_assign_footprint_to_users(minilib): # "R_0402_1005Metric" -> every 0402 resistor
def test_assign_unknown_is_library_wide(minilib): # Issue("error", None, "stale: …") -> library list
def test_check_js_hash_matches_data(minilib): # build; main(["check","--no-klc"]) -> check.js hash == data.js hash, klc false  (Review Focus 3)
def test_check_js_stale_after_change(minilib): # check, then edit a part + build -> hashes differ  (Review Focus 3)
```

- [ ] **Step 2: Run** `py -m pytest tests/test_review.py -v`. Expected: the new tests FAIL.
- [ ] **Step 3: Implement**; confirm the item format of real KLC issues by running `py -m libkit check` once and reading two symbol and two footprint items (adjust the matching if the format differs, and add a test with the real format).
- [ ] **Step 4: Run** `py -m pytest -q`; `py -m libkit build; py -m libkit check`. Expected: all pass; 0 errors; `build/review/check.js` exists.
- [ ] **Step 5: Commit** `libkit: check results on the review page`

---

### Task 9: Docs, browser check, end-to-end dry runs

**Files:**
- Modify: `CLAUDE.md` (Commands: `--local`; Layout: `build/review/`; Workflows: "Review page" paragraph, single add defaults for diodes/LEDs/transistors, local parts), `docs/superpowers/specs/2026-11-01-kicad-library-design.md` (§6.5 and §6.9: "Decided 2026-11-01 (Plan 4)" paragraphs with ⚑1–⚑8 as approved), `docs/superpowers/plans/2026-11-01-library-foundation.md` (plan series: Plan 4 done), `README` if it lists commands.

- [ ] **Step 1: Docs** as listed; CLAUDE.md stays terse, in its current style.
- [ ] **Step 2: Browser check.** `py -m libkit build; py -m libkit check`, then open `build/review/index.html` from disk (Claude in Chrome if available, otherwise the user). Verify, and report each item: no network requests (DevTools); search `100n` finds the 100 nF capacitors, `C1525` finds one part, `62k 0402` narrows to one; chips filter and combine with search; column chooser hides/shows and survives a reload; sort by stock; detail panel shows symbol + footprint SVG, all fields, check results, working links, both copy buttons; `#<name>` in the URL opens that part; dark mode readable (SVG card stays white); a description containing markup (temporary local edit, reverted after) shows as text; 900 px and phone width usable.
- [ ] **Step 3: End-to-end dry runs** (no `--write` without the user's OK): `py -m libkit add C81598 --footprint stock:Diode_SMD:D_SOD-123 --family Diode_SMD` and `py -m libkit add MountingHole_3.2mm_M3 --local --category mechanical --footprint stock:MountingHole:MountingHole_3.2mm_M3 --family MountingHole`. Show both reports and previews to the user.
- [ ] **Step 4: Run** `py -m pytest -q`; `py -m libkit build; py -m libkit check`; `git status --short`. Expected: all pass, 0 errors, nothing from `build/` or `.libkit/`.
- [ ] **Step 5: Commit** `doc: review page, discrete bases and local parts`
- [ ] **Step 6: Final review** — one fresh reviewer over the whole branch (`git diff main...plan4-review-gui`), fixes in a `libkit: final review fixes` commit, then ask the user before merging locally.

# Discrete Series Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `bulk-add discrete` adds whole MPN series of diodes (Zener, TVS, Schottky) with the dry run → table → `--write` flow. Single adds of diodes, LEDs and SOT-23 transistors find their stock KiCad footprint without options. The Diodes, LEDs and Transistors libraries then cover the Altium discretes plus the usual current parts.

**Architecture:**
- **One row per series value.** A series is an MPN pattern plus values, e.g. `BZT52C{}` with the `zener` list 2V4…51. For each value libkit searches JLC for that MPN and picks one part by the selection rules.
- **Each row reuses `add.prepare`.** prepare already does the footprint vendoring, `discretes.classify`, the base symbol and the pin/pad check, so every part matches what a single add produces.
- **Writes go through a new `add.apply_many`:** all files, one YAML rewrite per category, one build, and one rollback for the whole write.
- **Package map:** a new map from JLC's package text to a stock KiCad footprint (`discretes.stock_footprint`). Bulk uses it, and so does single `add` when `--footprint` is not given.
- **Unidirectional TVS** get base symbol `D_Zener`, as KiCad's stock library draws them (`Diode:SM6T6V8A`, `SMAJ*A`). Bidirectional TVS keep `D_TVS`.

**Tech Stack:** Python 3.12, pytest, existing JLC keyword search, `add.prepare`.

**Spec:** `docs/superpowers/specs/2026-11-01-kicad-library-design.md` (§6.4 single add, §6.6 selection rules, §6.7 bulk add). Plan series: `docs/superpowers/plans/2026-11-01-library-foundation.md` (Plan 8).

## Findings that shaped this plan (probed 2026-11-02)

- **JLC's Basic/Preferred discretes** come almost entirely from Chinese makers:
  - hongjiacheng (Preferred), with complete BZT52C, BZT52C…S, SMF, SMAJ and SMBJ series, stock 5k–3M per value;
  - CJ (JLC brand string "Jiangsu Changjing Electronics Technology Co., Ltd.", which is not `cjiang`);
  - MDD, KENTO (LEDs) and AOS.
  
  Nexperia, onsemi, Diodes Inc. and Vishay are nearly always Extended. The user allowed Chinese brands (2026-11-02).
- **Every TVS value is stocked.** All 40 values from 5.0 to 100 V of SMF/SMAJ/SMBJ …A and …CA have a part with stock ≥ 1000 at JLC.
- **"ST(Semtech)" is a Chinese brand, not STMicroelectronics.** It must not match STMicroelectronics.
- **Package spellings vary per maker:** `SMA(DO-214AC)`, `DO-214AC(SMA)`, `SMA`; `SOD-123FL` / `SOD-123F`; `SOT-23` / `TO-236`.
- **KiCad stock has no SMAF footprint.** SMAF parts (SS14F…) are left out.

## Decisions (user, 2026-11-02)

1. Chinese brands are fine: `manufacturers:` gains the discrete makers (Task 2).
2. Zener series: BZT52C (SOD-123) and BZT52C…S (SOD-323), 2V4–51V. BZX84C is dropped.
3. TVS series: SMF (SOD-123F), SMAJ (SMA) and SMBJ (SMB), each …A and …CA, 5.0–100 V.
4. Also: SS Schottky SMA (SS14…SS510), and about 70 single adds (switching/Schottky/rectifier diodes, ESD, LEDs, BJTs, small MOSFETs; see Task 4). Power MOSFETs come in a later batch.

## Global Constraints

- All Global Constraints of Plans 1–7 hold (UTF-8 + LF, no absolute paths, names never renamed, stock only in YAML, `build` + `check` 0 errors before a commit, tests offline, network only in dry runs).
- Rules (spec §6.6): Basic/Preferred before Extended; stock ≥ ~1000 for bulk; known manufacturers only; English datasheet preferred within a tier.
- Naming (CLAUDE.md): discretes by MPN (`mpn_name`), value = MPN.
- Commits: area prefix, short subject, at most two body lines, no Co-Authored-By trailer. Branch `plan8-discrete-series`, merged locally after the user's OK. Library content only after the user's OK on each table.

## Review Focus

1. **An MPN pattern that catches a neighbour series.** `BZT52C3V3` must not take `BZT52C3V3S` (SOD-323), and `SMAJ5.0A` must not take `SMAJ5.0CA`. Packaging suffixes like `BZT52C3V3-7-F` and `SMAJ5.0A/TR13` are the same part. → Task 3 `test_series_member`.
2. **Package spellings and wrong packages.** `SMA(DO-214AC)`, `DO-214AC(SMA)` and `SMA` are one footprint. A `SOD-123F` record in a `--package SOD-123` run is rejected with a note. → Task 1 `test_stock_footprint_spellings`, Task 3 `test_pick_rejects_other_package`.
3. **Brand look-alikes.** `ST(Semtech)` is not STMicroelectronics, and the CJ brand string is not `cjiang`. → Task 2 `test_discrete_manufacturers`.
4. **A value whose part has no base symbol** (dual diode, TVS of unknown polarity). The row is `none` with the reason. Bulk never fetches EasyEDA. → Task 3 `test_row_without_base_symbol`.
5. **A failure in the middle of a many-part write.** Nothing is left behind: files, YAML and the families declaration all roll back. The shared footprint is written once. → Task 3 `test_apply_many_rolls_back`.

---

### Task 1: Package map, TVS polarity, single-add default footprint

**Files:** Modify `tools/libkit/discretes.py`, `tools/libkit/add.py`. Test: `tests/test_discrete_series.py`.

**Interfaces — Produces:**
- `discretes.FOOTPRINTS: dict[str, tuple[str, str]]`: canonical package → (stock ref, family):

  | Canonical package | Stock footprint | Family |
  |---|---|---|
  | `SOD-123` | `Diode_SMD:D_SOD-123` | `Diode_SMD` |
  | `SOD-123F` | `Diode_SMD:D_SOD-123F` | `Diode_SMD` |
  | `SOD-323` | `Diode_SMD:D_SOD-323` | `Diode_SMD` |
  | `SOD-323F` | `Diode_SMD:D_SOD-323F` | `Diode_SMD` |
  | `SOD-523` | `Diode_SMD:D_SOD-523` | `Diode_SMD` |
  | `SOD-128` | `Diode_SMD:D_SOD-128` | `Diode_SMD` |
  | `SMA` | `Diode_SMD:D_SMA` | `Diode_SMD` |
  | `SMB` | `Diode_SMD:D_SMB` | `Diode_SMD` |
  | `SMC` | `Diode_SMD:D_SMC` | `Diode_SMD` |
  | `SOT-23` | `Package_TO_SOT_SMD:SOT-23` | `Package_TO_SOT_SMD` |
  | `SOT-323` | `Package_TO_SOT_SMD:SOT-323_SC-70` | `Package_TO_SOT_SMD` |
  | `SOT-363` | `Package_TO_SOT_SMD:SOT-363_SC-70-6` | `Package_TO_SOT_SMD` |
  | `LED-0603` | `LED_SMD:LED_0603_1608Metric` | `LED_SMD` |
  | `LED-0805` | `LED_SMD:LED_0805_2012Metric` | `LED_SMD` |
  | `LED-1206` | `LED_SMD:LED_1206_3216Metric` | `LED_SMD` |
- `discretes.canonical_package(part: JlcPart) -> str | None`:
  - accepts the spellings `SMA(DO-214AC)`, `DO-214AC(SMA)`, `DO-214AC`, `SMA`; `SMB(DO-214AA)`, `DO-214AA(SMB)`, `DO-214AA`; `SMC(DO-214AB)`, `DO-214AB(SMC)`; `SOD-123FL`, `SOD-123F`; `TO-236`, `SOT-23-3`, `SOT-23`; `SC-70-6(SOT-363)`, `TSSOP-6(SOT-363)`, `SOT-363`; `SOD-323(SC-90)`;
  - a chip size `0603`/`0805`/`1206` maps to `LED-…` only for LED records (classify category `leds_optoelectronics`);
  - anything else is None.
- `discretes.stock_footprint(part) -> tuple[str, str] | None` = `FOOTPRINTS[canonical_package(part)]`.

- [ ] **Failing tests:**
  - `test_stock_footprint_spellings`: the three SMA spellings → `Diode_SMD:D_SMA`; `SOD-123FL` → `D_SOD-123F`; `TO-236` → `SOT-23`; an LED record in `0603` → `LED_0603_1608Metric`; a resistor in `0603` → None; `SMAF` → None.
  - `test_unidirectional_tvs_is_zener_symbol`: a TVS record with `Polarity` `Unidirectional` and one channel → symbol `D_Zener`, category `diodes`, field `vr`. Bidirectional → `D_TVS`. Two channels → no base symbol.
  - `test_add_defaults_stock_footprint` (offline, fake resolve, minilib with the KiCad share dir as in the existing add tests): `prepare(root, "C8598")` without `--footprint` stages `LIB_Diode_SMD:D_SOD-123` and family `Diode_SMD`, with no EasyEDA fetch (the fake fetch raises).
- [ ] **Implement:**
  - `classify`: unidirectional TVS → `_make("diodes", "D_Zener", …)` with checklist `DIODE_CHECK`.
  - `add.prepare`: when `footprint` is None and `kind` is None and `stock_footprint(part)` is set, use `stock:<ref>` with `family` defaulting to the map's family. An explicit `--footprint` or `--family` still wins.
- [ ] `.venv\Scripts\python -m pytest -q` green; commit `libkit: stock footprints for discrete packages; unidirectional TVS as zener`.

### Task 2: Discrete manufacturers

**Files:** Modify `schema/library.yaml`. Test: `tests/test_discrete_series.py`.

- [ ] **Failing test `test_discrete_manufacturers`:** `canonical_manufacturer` maps
  - `"Jiangsu Changjing Electronics Technology Co., Ltd."` → `CJ`;
  - `"MDD(Microdiode Semiconductor)"` → `MDD`;
  - `"Hubei KENTO Elec"` → `KENTO`;
  - `"Alpha & Omega Semicon"` → `AOS`;
  - `"hongjiacheng"` → `hongjiacheng`;
  - `"STMicroelectronics"` → `STMicroelectronics`;
  - `"Vishay Intertech"` → `Vishay`.
  
  `"ST(Semtech)"` → None, and `cjiang` stays `cjiang` (not CJ).
- [ ] **Add, under a `# Discretes (plan 8)` comment:**
  - hongjiacheng;
  - CJ [Jiangsu Changjing Electronics Technology Co., Ltd., JCET];
  - MDD [MDD(Microdiode Semiconductor), Microdiode Semiconductor];
  - KENTO [Hubei KENTO Elec];
  - AOS [Alpha & Omega Semicon, Alpha & Omega Semiconductor];
  - Nexperia;
  - onsemi [ON Semiconductor];
  - Diodes Incorporated [Diodes Inc, Diodes];
  - Infineon [Infineon Technologies];
  - STMicroelectronics (no `ST` alias);
  - Texas Instruments;
  - ROHM [ROHM Semicon, ROHM Semiconductor];
  - Littelfuse;
  - Guangdong Hottech [Hottech];
  - XINGLIGHT;
  - Everlight [Everlight Elec];
  - Worldsemi;
  - and the Chinese makers that fill series gaps: BORN, LGE, GOODWORK, DOWO, Shandong Jingdao Microelectronics, TECH PUBLIC, FOSAN, JSMSEMI, Brightking, UMW [UMW(Youtai Semiconductor)].
  
  Also: `Vishay` gains the alias `Vishay Intertech`.
- [ ] Tests green; commit `lib: discrete manufacturers`.

### Task 3: `bulk-add discrete` by MPN series

**Files:**
- Create `tools/libkit/discrete_series.py`.
- Modify `tools/libkit/series.py` (named MPN value lists), `tools/libkit/pick.py` (`pick_discrete`), `tools/libkit/add.py` (`apply_many`; `apply` = `apply_many([plan])`), `tools/libkit/__main__.py`.
- Test: `tests/test_discrete_series.py`.

**Interfaces — Produces:**
- `series.MPN_VALUES`:
  - `zener` = 2V4 2V7 3V0 3V3 3V6 3V9 4V3 4V7 5V1 5V6 6V2 6V8 7V5 8V2 9V1 10 11 12 13 15 16 18 20 22 24 27 30 33 36 39 43 47 51;
  - `tvs` = 5.0 6.0 6.5 7.0 7.5 8.0 8.5 9.0 10 11 12 13 14 15 16 17 18 20 22 24 26 28 30 33 36 40 43 45 48 51 54 58 60 64 70 75 78 85 90 100.
  
  `--values` is a list name or a comma list (`14,16,110`).
- `discrete_series.series_member(pattern_mpn: str, mpn: str) -> bool`: true when `mpn` equals `pattern_mpn` case-insensitively, or continues with one of `- / , _` or a space (a packaging suffix).
- `pick.pick_discrete(mpn, package, parts, schema, lang=None, min_stock=1000) -> Pick`:
  - keeps series members whose `canonical_package == package`, known manufacturer, stock ≥ min_stock;
  - ranks Basic/Preferred before Extended, then English datasheet (as in `pick_ranked`), then stock;
  - the note names what was rejected (unknown manufacturer, low stock, other package).
- `discrete_series.plan(root, pattern, values, package, search=None, resolve_lang=None) -> list[bulk.Row]`:
  - one row per value: `exists` when an active part's `mpn` is a series member of that MPN, or its LCSC is in the library;
  - otherwise the pick, then `add.prepare(root, part.lcsc, footprint="stock:" + FOOTPRINTS[package][0], family=FOOTPRINTS[package][1], resolve=lambda _: part, fetch=<raises "needs a single add (no base symbol)">, klc=False)`;
  - a `ValueError` from prepare → row `none` with its message;
  - a prepared plan whose `entry["symbol"]` is not a base symbol → `none`.
- `discrete_series.apply(root, rows) -> int`: `add.load_plan` for every `new` row (ref = LCSC, the options prepare used), then `add.apply_many`.
- Plan file `.libkit/bulk-plan-discrete-<pattern with {} as x>-<package>.json`, saved and loaded like `bulk.save_plan`/`load_plan` (24 h, options, fingerprint = the active parts whose MPN is a member of any MPN of the run).
- CLI: `bulk-add discrete --mpn "BZT52C{}" --values zener --package SOD-123 [--write] [--skip 3V6,39]`. `--package` must be a `FOOTPRINTS` key. The table columns are those of the other kinds.

- [ ] **Failing tests:**
  - `test_series_member`: `BZT52C3V3` takes `BZT52C3V3-7-F` but not `BZT52C3V3S`; `SMAJ5.0A` takes `SMAJ5.0A/TR13` but not `SMAJ5.0CA`.
  - `test_pick_rejects_other_package`: a `SOD-123F` record in a `SOD-123` run is not picked, and the note says `package`.
  - `test_pick_discrete_order`: Preferred 10k beats Extended 1M; between two Preferred parts the higher stock wins; an unknown brand is never picked.
  - `test_row_without_base_symbol`: a fake dual-diode record → row `none`, and the fake fetch was not called.
  - `test_plan_and_write_discrete` (minilib + KiCad share): two Zener values → two `new` rows named by MPN with `vz`. Then `save_plan`/`load_plan`/`apply` → both parts in `parts/diodes.yaml`, `LIB_Diode_SMD.pretty/D_SOD-123.kicad_mod` written once, `Diode_SMD` declared, and `check(klc=False)` has 0 errors. A second dry run shows both as `exists`.
  - `test_apply_many_rolls_back`: the second of two plans has a broken entry → `apply_many` raises, and the YAML, footprints and `schema/library.yaml` are unchanged.
- [ ] Implement.
- [ ] Tests green; commit `libkit: bulk add of discrete MPN series`.

### Task 4: Docs, review, content

- [ ] CLAUDE.md:
  - commands: `bulk-add discrete --mpn … --values … --package …`;
  - workflow: series by MPN; singles of diodes, LEDs and SOT-23 transistors need no `--footprint` for mapped packages; dual diodes use `--symbol stock:Diode:BAV99` and the like.
  
  Spec §6.7 note and plan series. Commit `doc: discrete series`.
- [ ] One fresh reviewer over the branch; fixes; ask before merging.
- [ ] **Content:** each table goes to the user for OK.
  - **Series dry runs:**
    - `BZT52C{}` SOD-123 and `BZT52C{}S` SOD-323 (zener);
    - `SMF{}A`, `SMF{}CA` SOD-123F (tvs);
    - `SMAJ{}A`, `SMAJ{}CA` SMA (tvs);
    - `SMBJ{}A`, `SMBJ{}CA` SMB (tvs);
    - `SS{}` SMA `--values 14,16,110,24,26,210,34,36,310,54,56,510`.
  - **Singles (`add`):**
    - **Switching:** 1N4148W, 1N4148WS, BAS16, BAV99, BAV70, BAW56, BAV199.
    - **Schottky:**
      - BAT54A/C/S, BAT54WS, BAT54CW, BAS70, BAS70-04;
      - B5819W, B5819WS, BAT760, RB521S30;
      - NSR0240P2, PMEG6010ER, PMEG10020ELR, PMEG6030EP;
      - B560C, MBRD20100CT, MBR230LSF.
    - **Rectifiers:** M7, US1M, ES1D, ES1J, ES2J, ES3JB, US3MC.
    - **TVS:** SMBJ400CA (replaces P6SMB400CA).
    - **ESD:**
      - USBLC6-2SC6, USBLC6-4SC6Y, SRV05-4;
      - PESD5V0S1BL, ESD5Z5V0, TPD1E10B06, TPD4E05U06;
      - PESD1CAN, ESDCAN03-2BWY, PRTR5V0U2X, ESDA6V1L;
      - PTVS5V0S1UR, SP0503BAHTG.
    - **LEDs:** KENTO KT-0603/0805/1206 in R/G/B/Y/W, WS2812B-2020, WS2812B-5050, XL-1615RGBC.
    - **BJTs:** MMBT3904/3906, MMBT2222A/2907A, BC847C, BC857C, BC817-40, BC807-40, SS8050, SS8550, BC847BS, MMDT3904, DTC114EKA.
    - **MOSFETs:** 2N7002, 2N7002DW, BSS138, BSS138BK, BSS84, BSS123, AO3400A, AO3401A, SI2301CDS, DMG2305UX, DMP2035U, IRLML2502.
  - The earlier starter-set mechanical parts (mounting holes, test point, fiducial) are shown again with them.

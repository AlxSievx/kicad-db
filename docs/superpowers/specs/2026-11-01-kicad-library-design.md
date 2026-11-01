# Personal KiCad Part Library — Design

Date: 2026-11-01
Status: draft, awaiting approval

## 1. Intent

Build a personal KiCad 10 part library that every one of my boards draws its
parts from. It replaces my Altium setup (Postgres DbLib + PyQt manager), which
in turn replaced a hand-edited xlsx that was messy. The point of the whole
thing is **structure and completeness**: every part is a real, orderable part
with full data (manufacturer, MPN, JLC/LCSC number), and every symbol and
footprint follows one uniform style.

Day-to-day work on the library is done **by Claude** (bulk-adding passives,
adding a part from an MPN or C-number). I review the result with a small
read-only GUI and in KiCad itself.

Initially private and used only by me; later possibly shared with friends, so
it must be portable (no machine-specific paths, no server, no credentials).

## 2. Goals

- One master copy of all part data, as text, tracked in git, diffable.
- Every part complete: Manufacturer, MPN, LCSC number, JLC type
  (Basic/Preferred/Extended), datasheet URL, plus the category's own parameters.
- Broad categories (search-driven use); typing `100nF`, `100n`, an MPN or a
  C-number in KiCad's symbol chooser finds the part.
- Claude can:
  - **bulk-add passives** ("all E24 resistors 1k–1M, 0402, 1%"), picking a
    good, available JLC part per value by the quality rules (§6);
  - **add a single part** from an MPN or LCSC C-number, including symbol,
    footprint and 3D model;
  - **re-check stock** for the whole library and flag parts that went out of
    stock or obsolete.
- Uniform, clean symbols and footprints, checked automatically where possible
  (KiCad Library Convention checks).
- 3D models included in the repo.
- A read-only review GUI (layout "A": searchable table + detail panel).
- Installable in KiCad 10 by adding one nested-table entry per library type.

## 3. Non-goals

- No database, no ODBC, no server of any kind.
- No migration of the existing Altium parts — the library starts empty.
- No datasheet PDFs in the repo — only URLs.
- No editing inside the GUI; changes go through Claude (or a text editor).
- No support for KiCad < 10.
- No multi-user workflow, permissions or release process yet.
- No second-source / alternate-MPN handling per part (one row = one MPN).

## 4. Anti-goals (would be a failure even if it "works")

- Part data drifting back to hand-edited mess: inconsistent field names,
  missing MPNs, free-text values in random formats.
- A part in the library without MPN + LCSC number.
- Footprints in mixed styles (line widths, layers, naming, origins).
- A library change silently altering an existing board. (KiCad embeds symbols
  and footprints in the design; part names must never be renamed or reused
  once added — deprecate instead.)
- Credentials or machine-specific absolute paths in the repo (the Altium repo
  has its Postgres password in `README.md` and the `.udl` — not again).

## 5. Approaches considered

All approaches share: YAML per category as master data, a build script that
generates what KiCad reads, and a GUI reading the same YAML.

| | Approach | Trade-off |
|---|---|---|
| 1 | Generate SQLite + `.kicad_dbl` (database library, like CERN) | Closest to Altium; few generic symbols. Needs SQLite ODBC driver on every PC; KiCad DB libs still have rough edges (caching, load speed). |
| **2** | **Generate native `.kicad_sym` libraries (chosen)** | Each part is a full symbol with all fields, derived from shared base symbols. No driver, behaves like KiCad's stock libs, easiest to share. Generated files are larger, but they're machine-written anyway. |
| – | Hand-made symbols in KiCad, no YAML | Dropped: recreates the messy-xlsx problem. |
| – | SQLite as master copy | Dropped: binary in git, no diffs. |

**Chosen: 2**, because the database's only real job (structured, tabular part
data) is already covered by YAML + Claude + GUI, and native libraries need
nothing installed beyond KiCad.

## 6. Decisions

### 6.1 Repository layout (my call)

```
kicad-db/
├─ CLAUDE.md                  # how Claude works on this library (rules, workflows)
├─ README.md                  # install + usage for humans
├─ parts/                     # MASTER DATA — one YAML per category
│  ├─ resistors.yaml
│  ├─ capacitors.yaml
│  └─ ...
├─ schema/                    # field definitions per category (required/optional, units)
├─ src/
│  └─ symbols/                # hand-curated base & unique symbols (input to the build)
│     ├─ passives.kicad_sym   #   base symbols R, C, C_Polarized, L, FB ...
│     └─ <category>.kicad_sym #   unique IC/connector symbols, cleaned after import
├─ symbols/                   # GENERATED — LIB_<Category>.kicad_sym, committed
├─ footprints/                # curated, one .pretty per package family
│  └─ LIB_<Family>.pretty/
├─ 3dmodels/                  # STEP files, one .3dshapes per footprint family
│  └─ LIB_<Family>.3dshapes/
├─ sym-lib-table              # nested table, entries use ${LIB_DIR}
├─ fp-lib-table
├─ tools/                     # Python: build, check, import, bulk-add, stock refresh, GUI
└─ build/                     # GENERATED, gitignored: review GUI page, preview SVGs, caches
```

Generated symbol libraries are **committed**, so a friend can clone and use the
library without running Python. `tools/check` fails if they're out of date.

`LIB` is the library prefix (decided: plain `LIB`, no personal name).

### 6.2 Categories (symbol libraries) (my call, open to change)

Broad, ~15, because use is search-driven:

Resistors · Capacitors · Inductors (incl. ferrite beads) · Diodes (incl. TVS,
Zener, Schottky) · LEDs & Optoelectronics · Transistors · ICs Power ·
ICs Analog · ICs Digital & MCU · ICs Interface · Crystals & Oscillators ·
Connectors · Switches & Relays · Protection (fuses, PTC) · Mechanical
(mounting holes, test points, fiducials) · Modules.

Adding a category later is allowed; the bar is "doesn't fit anywhere".
File and nickname form: no spaces or `&`, e.g. `LIB_LEDs_Optoelectronics`,
`LIB_ICs_Power`.

### 6.3 Footprint libraries (my call)

Organised by **package family**, not by part category, because one package
(e.g. SOT-23) serves transistors, regulators and ESD diodes alike. Families
mirror KiCad stock naming: Passives_SMD (R/C/L chips), Package_SO,
Package_SOT, Package_DFN_QFN, Package_QFP, Package_BGA, Package_TO,
Connectors, Crystals, Mechanical, … created as needed.

Footprint names follow KiCad Library Convention (KLC), e.g.
`C_0402_1005Metric`, `SOIC-8_3.9x4.9mm_P1.27mm`.

3D models: STEP, referenced as `${LIB_DIR}/3dmodels/...`.

JLC assembly rotation (my call): footprints in KLC orientation often need a
rotation correction in JLC's placement file. Each footprint family can carry an
optional `jlc_rotation` offset in a small table in `schema/`, so a later
BOM/CPL export can apply it. Export itself is out of scope for now.

### 6.4 Part data model

One YAML entry per orderable part. Key = part name, unique across the library,
never renamed once added.

**Common fields (required unless noted):**

| Field | Example | Notes |
|---|---|---|
| name | `C_100n_0402_16V_X7R` / `TPS62130RGTR` | Passives: `<Prefix>_<Value>_<Pkg>_<key params>`; others: MPN |
| category | Capacitors | |
| symbol | `C` | base symbol (shared) or unique symbol in `src/symbols` |
| footprint | `LIB_Passives_SMD:C_0402_1005Metric` | must exist |
| value | `100nF` | normalised notation per unit |
| description | `100nF 16V X7R ±10% 0402 MLCC` | generated if omitted |
| manufacturer | Samsung | from a known-manufacturer list (§6.6) |
| mpn | CL05B104KO5NNNC | |
| lcsc | C1525 | |
| jlc_type | Basic / Preferred / Extended | |
| datasheet | URL | |
| status | active / deprecated | deprecated parts stay in their library (removing would break "update from library" on old boards); build prefixes their description with `DEPRECATED` and drops their keywords so search doesn't surface them |
| stock, stock_checked | 48200000, 2026-10-30 | YAML + GUI only, **not** written into symbols |

**Category fields (examples; full list lives in `schema/`):**
- Resistors: resistance, tolerance, power, tempco
- Capacitors: capacitance, voltage, dielectric, tolerance
- Inductors: inductance, current_rating, current_sat, dcr
- Diodes: vr, if, vf
- Transistors: type, vds/vce, id/ic, rds_on

**Generated into each symbol:** Reference, Value, Footprint, Datasheet,
Description, Manufacturer, MPN, LCSC, JLC_Type, category fields, and
**Keywords** built automatically from the data: value in several spellings
(`100nF 100n 0.1uF`), MPN, LCSC number, package, key params. Keywords are never
typed by hand.

### 6.5 Symbols (my call)

- Shared parts (R, C, L, LED, diodes, common transistors) are KiCad **derived
  symbols** (`extends`) of a base symbol; the base is copied into each
  generated category library (KiCad requires base and derived in the same
  file).
- Unique parts (ICs, connectors) have their own symbol in `src/symbols`,
  created by import + cleanup; the build writes it out with all fields set.
- Uniform style: 100 mil (2.54 mm) pin grid, 1.27 mm text, fixed field order,
  only Reference + Value visible on placement.

Decided 2026-11-01 (Plan 4): discrete bases copied unchanged from KiCad stock (`D`, `D_Schottky`,
`D_Zener`, `D_TVS`, `LED`, and the SOT-23 pinouts `Q_NMOS_GSD`, `Q_PMOS_GSD`, `Q_NPN_BEC`,
`Q_PNP_BEC`, since `Device:Q_NMOS` numbers its pins D/G/S); mechanical bases `MountingHole`,
`MountingHole_Pad`, `Fiducial`, `TestPoint`. `add` uses a base only when JLC's record and the
footprint's pads show it fits; unidirectional TVS has no base. Parts without a C-number (non-orderable
categories) are added with `add --local`. `check` compares symbol pins with footprint pads.

### 6.6 Part selection rules (decided together)

For automatic picks (bulk add, "find me a part for X"):
1. JLC **Basic or Preferred** before Extended; Extended only if nothing fits.
2. Stock: **≥ ~1000 for bulk-added passives**. For single parts I name myself:
   any stock > 0 is accepted, with a warning below ~100.
3. **Known manufacturers only** (list in repo, e.g. Samsung, Murata, Yageo,
   UNI-ROYAL, TDK, …; extendable).
4. Ceramic capacitors: **C0G/NP0, X7R or X5R**, never Y5V/Z5U (C0G/NP0 added 2026-11-01: JLC's Basic small values are C0G, the better dielectric there).
5. Bulk adds show the full list for confirmation before anything is written.
6. English datasheet preferred within the same JLC tier; bilingual counts as
   English; a preference, never a reason to skip a value (added 2026-11-01).
   A Mouser part number/datasheet as second source is deferred (needs an API key).

These rules live in `CLAUDE.md` so every Claude session applies them the same
way.

### 6.7 Workflows

**Single add (C-number or MPN):**
1. Resolve to an LCSC part; fetch data (manufacturer, MPN, package, stock, JLC
   type, datasheet URL, parameters).
2. If the needed footprint/symbol doesn't exist yet: download via
   **easyeda2kicad** (symbol, footprint, 3D model).
3. Normalise automatically: KLC name, layers and line widths, fab outline +
   `${REFERENCE}` on Fab, courtyard, fixed field set, 3D path via
   `${LIB_DIR}`, strip easyeda leftovers.
4. Run checks (§6.8); report to me what needs a human look (pin layout, pad
   sizes vs datasheet).
5. Write the YAML entry, build, commit after my OK.

Decided 2026-11-01 (Plan 3): KiCad's stock symbol/footprint is preferred when
one exists; EasyEDA output is the fallback. EasyEDA footprints keep EasyEDA's
orientation, which is JLC's placement orientation (no automatic rotation to
KLC's pin-1-top-left). Only STEP models are kept. Ferrite beads live in
Inductors as `FB_<impedance>_<pkg>_<current>`; non-chip inductors are named by
MPN. Unknown brands on single adds are kept, not added to the known list.

**Bulk add (passives):** generate the value list → pick per value by §6.6 →
show list → on confirmation write YAML → build → check.

**Stock refresh:** re-query all parts, update `stock`/`stock_checked`, report
parts below threshold, out of stock or obsolete.

**JLC data source:** to be chosen by the builder after verifying candidates —
e.g. the public jlcparts dataset (full catalogue with stock and Basic/Extended
flag, good for bulk), the EasyEDA/LCSC endpoints easyeda2kicad already uses,
or a JLC search API. Requirements: stock, JLC type, MPN, manufacturer,
package, datasheet URL, parametric attributes for passives. No account or API
key that would have to live in the repo.

### 6.8 Checks (`tools/check`)

- YAML valid against schema; required fields present; names unique.
- Referenced base symbol, footprint and 3D model exist.
- Generated symbol libraries up to date with YAML.
- Footprints and symbols pass KiCad's KLC check scripts
  (kicad-library-utils), with an explicit allow-list for justified exceptions.
- No absolute paths anywhere in library files.

### 6.9 Review GUI (layout A, my call on technology)

- A **single static HTML page** generated by the build into `build/`, opened by
  double-click; no server.
- Search box over all fields, category filter chips, column chooser.
- Table: name, value, package, key params, manufacturer, MPN, LCSC, JLC type
  (colour tag), stock (warning colours).
- Detail panel on row click: symbol + footprint preview (SVG rendered with
  `kicad-cli`), all fields, check results, links: datasheet, JLC/LCSC page,
  copy MPN.
- Read-only.

Decided 2026-11-01 (Plan 4): `build/review/index.html` plus `data.js` (from `build`), `check.js`
(from `check`, stamped with a hash of the part data so stale results are marked) and `svg/`
previews, cached per library. No network, no `fetch()`; works from `file://`. Without `kicad-cli`
the page has no previews.

### 6.10 Installation in KiCad 10

1. Clone the repo.
2. Preferences → Configure Paths: add `LIB_DIR` → repo folder.
3. Manage Symbol Libraries: add one entry, type **Table**, path
   `${LIB_DIR}/sym-lib-table`; same for footprints with `fp-lib-table`.

### 6.11 Environment

- KiCad 10.0 (installed), Python 3 (3.15 installed), git.
- Python deps (easyeda2kicad, PyYAML, pypdf + cryptography for the datasheet
  language check, kicad-library-utils) installed in a
  project-local virtual environment; versions pinned. If a dependency doesn't
  support Python 3.15 yet, the builder may use an older Python for the venv.
- Git: Claude commits library changes only after my OK on each add.

## 7. Left to the builder

- Exact YAML schema format and validation library.
- Choice and verification of the JLC data source (§6.7).
- Exact normalisation rules for imported footprints/symbols, within §6.3/§6.5.
- Value notation per unit (e.g. `100nF` vs `100n` as stored value) — pick one,
  keep all spellings in Keywords.
- GUI implementation details within §6.9.
- Initial content: which passives to bulk-add first is a separate request.

## 8. Open questions

None.

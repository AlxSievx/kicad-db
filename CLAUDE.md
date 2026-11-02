# LIB — personal KiCad 10 part library

Every board takes its parts from this library. Each part is one real,
orderable part with full data (manufacturer, MPN, LCSC/JLC number). Claude
does the day-to-day work (bulk adds, single adds); the user reviews.

Design: `docs/superpowers/specs/2026-11-01-kicad-library-design.md`.

## Layout

- `parts/<category>.yaml` — **master data**, one file per category. Edit these.
- `schema/library.yaml` — categories, fields, footprint families, known manufacturers.
- `schema/klc-allowlist.yaml` — KLC rules deliberately not enforced, each with a reason.
- `src/symbols/*.kicad_sym` — base symbols (shared, e.g. R, C) and unique symbols (ICs).
- `footprints/LIB_<Family>.pretty/`, `3dmodels/LIB_<Family>.3dshapes/` — curated, by package family.
- `symbols/`, `sym-lib-table`, `fp-lib-table` — **generated, committed. Never edit by hand.**
- `tools/libkit/` — the tooling; tests in `tests/`.
- `.libkit/` — local, not committed: bulk-add dry runs, single-add staging (`add/<REF>/`), datasheet-language cache.
- `build/` — local, not committed: review page `build/review/index.html` (written by `build`, check results by `check`), KLC checker.

## Commands (PowerShell, repo root)

```
.venv\Scripts\python -m libkit build        # regenerate symbols/ and the library tables
.venv\Scripts\python -m libkit check        # data, references, stale files, absolute paths, KLC
.venv\Scripts\python -m libkit fetch-klc    # once per clone: install the pinned KLC checker
.venv\Scripts\python -m libkit vendor-sym Device:C --into passives
.venv\Scripts\python -m libkit vendor-fp Capacitor_SMD:C_0402_1005Metric --family Passives_SMD
.venv\Scripts\python -m pytest
.venv\Scripts\python -m libkit jlc C1525          # look up one LCSC part (network)
.venv\Scripts\python -m libkit bulk-add resistor --series E24 --from 1k --to 1M --package 0402 --tolerance 1%
.venv\Scripts\python -m libkit bulk-add capacitor --series E6 --from 1n --to 1u --package 0402 --tolerance 10% --voltage 16V
.venv\Scripts\python -m libkit bulk-add resistor --series E6 --from 1mR --to 100mR --package 2512 --tolerance 1% --min-power 1W
.venv\Scripts\python -m libkit bulk-add tantalum --series E6 --from 1u --to 470u --case A          # cases A–D
.venv\Scripts\python -m libkit bulk-add electrolytic --series E6 --from 1u --to 1000u --can 6.3x7.7  # 5x5.4 … 10x10.5
.venv\Scripts\python -m libkit bulk-add bead --series FB --from 30 --to 2200 --package 0603      # bead impedances @100MHz
.venv\Scripts\python -m libkit bulk-add inductor --series E6 --from 1u --to 10u --package 0805   # chip inductors
.venv\Scripts\python -m libkit bulk-add inductor --series E6 --from 1u --to 470u --family SWPA4030S  # power-inductor series
.venv\Scripts\python -m libkit bulk-add discrete --mpn "BZT52C{}" --values zener --package SOD-123   # MPN series: zener, tvs, or "14,16,110"
.venv\Scripts\python -m libkit refresh-stock      # re-query stock + JLC type of every part (network)
.venv\Scripts\python -m libkit find resistor 62k --package 0402 --tolerance 1%   # candidates for one value (network)
.venv\Scripts\python -m libkit add C1046         # single add, dry run (network); --write applies it
.venv\Scripts\python -m libkit add C6186 --category ics_power --family Package_TO_SOT_SMD --fp-name SOT-223-3_TabPin2
.venv\Scripts\python -m libkit add C81598         # diode/LED/SOT-23 transistor: stock footprint, category + base symbol automatic
.venv\Scripts\python -m libkit add MountingHole_3.2mm_M3 --local --category mechanical --footprint stock:MountingHole:MountingHole_3.2mm_M3 --family MountingHole
```

Only `jlc`, `bulk-add` (dry run), `refresh-stock`, `find` and `add` (dry run) use the network; transient
errors (timeouts, HTTP 429/5xx) are retried 3 times (2 s, 5 s, 15 s apart). Tests never touch the network;
live tests are opt-in: `$env:LIBKIT_LIVE=1; .venv\Scripts\python -m pytest -k live`.

## Workflows

- **Single lookup:** `libkit jlc C…` prints JLC's record (MPN, brand, stock,
  Basic/Preferred/Extended, datasheet, attributes), the canonical
  manufacturer name, or `unknown` (then the brand is not in `manufacturers:`),
  and the datasheet language (`en`, `zh`, `unknown`).
- **Bulk add (resistors, capacitors):** always run the dry run first (no
  `--write`) and show the user the whole table. The dry run is saved in
  `.libkit/bulk-plan-<kind>-<package>.json` (one per kind and package, so several tables can be approved together); after their OK, the same command with `--write`
  writes exactly those rows (no new picks, no network) into
  `parts/<category>.yaml`, then builds. `--write` refuses when the options
  differ, the dry run is older than 24 h, or the library's parts of that kind and package changed since; then
  dry-run again and show the new table. Values the user wants left out:
  `--write --skip 62k,1.8k` (typos are refused). Then run `check` and commit. Rows:
  `new` = will be added, `exists` = an existing part covers the value (or the
  pick's name/LCSC is already in the library), `none` = no part meets the rules
  (see the note). Column `ds` = datasheet language. `--dielectric` defaults to
  `C0G,NP0,X7R,X5R`.
  Capacitors below 10pF are not needed (user decision): start series at 10p.
  Chip sizes: 0402, 0603, 0805, 1206, 1210, 2512. `--min-power 1W` filters resistors (shunts).
  Tantalum (`--case A|B|C|D`) and SMD electrolytic (`--can 5x5.4|6.3x5.4|6.3x7.7|8x10.5|10x10.5`):
  one part per value and size, the highest voltage within the best JLC tier (user decision);
  candidates come from JLC's keyword search, `--tolerance`/`--voltage` are optional filters.
  Beads (`--series FB`: 30R…2200R @100MHz) and chip inductors (`--package`): one part per value,
  the highest current within the best JLC tier. Power inductors: whole manufacturer series per size
  (`--family SWPA4030S`, Sunlord SWPA 3015S/4030S/5040S/6045S/8040S chosen 2026-11-01); import the
  family footprint once with `add <C…> --category inductors --family Inductor_SMD --fp-name
  L_Sunlord_<family>` (show the preview), then bulk-add; parts are named by MPN.
  Add full series, not single values (user rule).
- **Bulk add (discretes):** `bulk-add discrete --mpn "SMAJ{}A" --values tvs --package SMA`: one row per
  MPN (pattern with the value code), packaging suffixes like `-7-F` or `/TR13` count as the same part,
  neighbour series (`BZT52C3V3S`) do not. Each row is built like a single add (stock footprint of
  `--package`, base symbol); a part that needs its own symbol is a `none` row: add it singly. Same dry run /
  `--write` / `--skip 3V6,39` flow, plan file `.libkit/bulk-plan-discrete-<pattern>-<package>.json`.
  `--values` lists: `zener` (2V4…51), `tvs` (5.0…100); in PowerShell quote a comma list (`"5.0,24"`).
  Packages: SOD-123, SOD-123F, SOD-323, SOD-323F, SOD-523, SOD-128, SMA, SMB, SMC, SOT-23, SOT-323, SOT-363,
  LED-0603/0805/1206.
- **Find (one value):** `libkit find <resistor|capacitor|inductor|bead> <value> --package …`
  lists candidates ordered by the rules (Basic/Preferred, then stock), with notes
  where a part misses the bulk rules (`Extended`, `stock < 1000`, unknown
  manufacturer, already in the library). Use it when the user names a value,
  not a part; propose one C-number per value and wait for their OK.
- **Single add:** `libkit add <C…|MPN>` is a dry run: it prints the YAML entry,
  the files it would create, warnings, notes, KLC results and preview SVGs
  (`.libkit/add/<REF>/preview/`), and stages everything in `.libkit/add/<REF>/`.
  Show the user that report (and the previews); after their OK, the same
  command with `--write` applies exactly the staged plan (no network), builds,
  and rolls back on failure. Then `check` and commit. An ambiguous MPN lists
  the C-numbers to choose from.
  - Chip passives (0402–1206 R, C, L, ferrite beads) need no options: base
    symbol + `LIB_Passives_SMD`.
  - Diodes, LEDs, transistors: no `--footprint` needed for the packages above (KiCad stock footprint);
    dual diodes and the like: `--symbol stock:Diode:BAV99`. Category from JLC's part type; base symbol (`D`, `D_Schottky`, `D_Zener`,
    `D_TVS` (unidirectional TVS: `D_Zener`), `LED`, `Q_NMOS_GSD`, `Q_PMOS_GSD`, `Q_NPN_BEC`, `Q_PNP_BEC` in `src/symbols/discretes.kicad_sym`;
    power MOSFET bases see below)
    only for a single device whose footprint pads fit (transistors: SOT-23-like packages only); otherwise
    the EasyEDA symbol, with a note why. Check the pad order the note names (pad 1 = cathode, G/S/D, B/E/C).
  - Everything else needs `--category`, and a new footprint needs `--family`.
    **Source preference:** KiCad's stock library first
    (`--symbol stock:<Lib>:<Name>`, `--footprint stock:<Lib>:<Name>`), else
    EasyEDA (the default) with `--fp-name` in KLC form (`SOT-223-3_TabPin2`).
    Existing LIB items: `--symbol <src symbol>`, `--footprint LIB_<Family>:<Name>`.
    Family names are KiCad stock library names: `Package_TO_SOT_SMD`, `Package_SO`,
    `Package_DFN_QFN`, `Inductor_SMD`, `Connector`, …
  - EasyEDA footprints keep EasyEDA's (= JLC's) orientation; the report says
    when pin 1 is not top-left. Only STEP models are kept.
  - Remaining KLC errors on an imported symbol (S4.2 pin placement, S4.4 pin
    types): `--pin-types EN=input,#4=passive`, a hand edit of the symbol in
    `src/symbols/` after `--write`, or an allow-list entry with a reason, each
    with the user's OK. KLC errors on stock KiCad content are reported as they are.
  - Unknown brands are kept (without the `(…)` suffix) with a warning; they
    are not added to `manufacturers:` (that list is for automatic picks).
  - `add` refuses a symbol pin without a footprint pad of that number (`check` reports it too).
    The reverse is NOT checked: a pad without a symbol pin (typically an exposed pad) stays
    unconnected. Look at the pad numbers of every new footprint (`grep '(pad '` in the staged
    `.kicad_mod`) and pick the symbol whose pins cover all of them.
  - EasyEDA pad numbering is not uniform, even within one package: extra copper (source bar,
    exposed pad) may repeat a lead number (`3`, `8`) or get its own (`9`). Fix by choosing the
    symbol, or with the user's OK by renumbering the pad in `footprints/` after `--write`
    (e.g. exposed drain pad `9` → `8` for `AP30H80Q`), then `build` + `check`.
  - A footprint name that already exists is reused **without comparing geometry**
    (`reusing existing footprint`). Only give an existing `--fp-name` when the package is really the same.
  - KLC findings on stock KiCad footprints/symbols copied unchanged (and the legacy pin stacks of the
    multi-lead MOSFET bases) are allow-listed in `schema/klc-allowlist.yaml` with a reason, after the
    user's OK, so `check` stays at 0 errors and 0 warnings. Missing stock 3D model: add without one.
- **Power MOSFETs** (single adds, all Extended at JLC: pick on stock and brand). Base symbols in
  `src/symbols/discretes.kicad_sym`, chosen by the footprint's pad numbers:
  `Q_[NP]MOS_GDS` (TO-252: 1 G, 2 tab D, 3 S), `Q_[NP]MOS_SSSGD` (1–3 S, 4 G, one drain pad 5: KiCad's
  `TDSON-8-1`, `LFPAK56`, `LFPAK33`, `PowerPAK_SO-8(L)_Single`, `Vishay_PowerPAK_1212-8_Single`,
  `ONSemi_SO-8FL_488AA`), `Q_[NP]MOS_SSSGDDDD` (SO-8 `SOIC-8_3.9x4.9mm_P1.27mm`, and EasyEDA
  footprints with drain pads 5–8). Dual SO-8: `--symbol stock:Transistor_FET:Q_Dual_[NP]MOS_S1G1S2G2D2D2D1D1`.
  Example: `add C534384 --category transistors --symbol Q_NMOS_SSSGD --footprint stock:Package_TO_SOT_SMD:TDSON-8-1 --family Package_TO_SOT_SMD`.
  Infineon TSDSON-8FL (BSZ…): `--symbol Q_NMOS_SSSGDDDD --family Package_SON --fp-name Infineon_PG-TSDSON-8-FL_3.3x3.3mm_P0.65mm`.
  Set per package: N 30/40/60/80/100(/150/200) V, P 20/30/40/60(/80/100) V.
- **Local parts (no C-number):** `libkit add <name> --local --category mechanical --footprint stock:…
  --family …` (no network; non-orderable categories only). Symbol from the footprint library
  (`MountingHole`, `MountingHole_Pad` for `*_Pad`, `Fiducial`, `TestPoint`; else `--symbol`), value = name
  unless `--value`, description = the footprint's unless `--description`. Same dry run / `--write` flow.
- **Review page:** `build` writes `build/review/index.html` (open by double-click; search, category chips,
  columns, detail panel with symbol/footprint previews from `kicad-cli`, fields, links). `check` adds its
  results; the page says when they are older than the data. Point the user to it after adds.
- **Stock refresh:** `libkit refresh-stock` updates `stock`, `stock_checked`
  and `jlc_type` of every part and lists what needs a look (`not_found`,
  `out_of_stock`, `low_stock`, `type_changed`, `mpn_changed`). It rebuilds when
  a JLC type changed. Report the list to the user before committing.

## Rules

- Run `build` and then `check` before every commit. `check` must report 0 errors.
- Commit library changes only after the user's OK on each add.
- Never rename or reuse a part name once it exists. To retire a part, set `status: deprecated`.
- Never write credentials or absolute paths anywhere. Every library path goes through `${LIB_DIR}`.
- Datasheets are links only: JLC's `dataManualUrl` (an LCSC page that shows the PDF); `bulk-add` fills it in.
  Fallback when JLC has none: `https://www.lcsc.com/datasheet/<LCSC>.pdf`.
  `datasheet_lang` (YAML only) records the language libkit found behind the link.
- `stock` / `stock_checked` live in YAML only; they are never written into symbols.
- Quote values YAML could misread, e.g. `package: "0402"`. The loader keeps strings anyway, but quoting makes intent clear.
- JLC attribute values that hold two numbers (`13A、50A` = ambient, case) are fixed by hand in YAML to the
  datasheet's headline value (`50A`), then `build`.

## Working with the user

- Show every table, dry-run report and preview, and wait for the user's OK before any `--write`.
- Add **full series**, not single values. Chinese brands are fine.
- Code changes (`tools/libkit/`): write a plan in `docs/superpowers/plans/` first; the user reviews it.
  Then execute natively (inline) on a feature branch, one fresh opus reviewer at the end, merge locally after
  the user's OK. The user pushes themselves (`! git push`).
- Content-only changes (new base symbols, allow-list entries, parts) need no plan, only the user's OK.

## Altium reference (old library)

Goal: LIB eventually covers every part of the user's Altium DbLib (SciMo Postgres, table `"Parts$"`,
~1965 rows). **Read only**: never modify it, never commit its data, never copy its password. The
connection settings are in the Altium library manager's `config.json` (path in Claude's project memory,
not in the repo: no absolute paths; read it at runtime, connect with `default_transaction_read_only=on`); dump `SELECT * FROM "Parts$"` to a CSV in the
session scratchpad only. For every Altium part: check stock and whether it is outdated, and propose better or
more current stocked alternatives. Altium symbols/footprints may be copied but must be normalised to LIB style.
Most Altium ICs (188/307) and connectors have no LCSC number (Plan 9: orderable parts without LCSC).

## Open items (deferred)

- Plan 8 review minors: bulk rows drop the pad-order note; no fallback to the next candidate when the top
  pick fails classify/prepare; TO-236 transistors get no base symbol; bulk and single add share
  `.libkit/add/<LCSC>` staging; duplicate `--values` not deduplicated; misleading "no candidates" note when
  JLC returned only neighbour series; `--package` silently ignored for tantalum/electrolytic.
- `add`: footprint reuse by name without a geometry check; no check for pads without a symbol pin.
- Power MOSFETs: auto symbol/footprint by package (now explicit options); native KiCad 10 pin stacks
  (needs pin/pad check support).
- JLC BOM/CPL export: plan written (`docs/superpowers/plans/2026-11-01-jlc-export.md`), on hold.
- Not yet added from Altium: IXTY08N100D2 (no stock), AO4606-type N+P pairs, TO-220/TO-263/SiC MOSFETs,
  SOT-23 MOSFETs SQ2361CES, SI2324DS, DMP3099L.

## Part naming

Names may only contain letters, digits and `_ - . + ,` (KLC G1.1). Write `%` as `pct`.

| Category | Pattern | Example |
|---|---|---|
| Capacitors | `C_<value w/o F>_<pkg>_<voltage>_<dielectric>` | `C_100n_0402_16V_X7R` |
| Resistors | `R_<value>_<pkg>_<tol>pct` (below 1R: `mR`) | `R_10k_0402_1pct`, `R_10mR_2512_1pct` |
| Tantalum caps | `C_<value w/o F>_Case<X>_<voltage>_Ta` | `C_10u_CaseA_16V_Ta` |
| Electrolytic caps | `C_<value w/o F>_D<d>x<h>_<voltage>_Al` | `C_100u_D6.3x7.7_35V_Al` |
| Inductors (chip, 0402–1206) | `L_<value w/o H>_<pkg>_<current>` | `L_10u_0805_15mA` |
| Inductors (other packages) | the MPN, value `10uH` | `MWSA0503S-100MT` |
| Ferrite beads (in Inductors) | `FB_<impedance>_<pkg>_<current>`, value `100R@100MHz` | `FB_100R_0805_800mA` |
| Everything else | the MPN (characters outside the set above become `_`) | `TPS62130RGTR` |

Value notation (`value:` field): resistors `10mR`, `100R`, `4.7k`, `1M` (`mR` = milliohm,
`M` = megaohm); capacitors `10pF`, `100nF`, `4.7uF`, `1000uF` (never `mF`); inductors `10uH`. Other spellings are generated into
the search keywords automatically.

## Part selection rules (automatic picks: bulk add, "find me a part for X")

1. JLC **Basic or Preferred** before Extended; Extended only if nothing fits.
2. Stock: **≥ ~1000 for bulk-added passives**. For single parts the user names:
   any stock > 0 is accepted, with a warning below ~100.
3. **Known manufacturers only** (`manufacturers:` in `schema/library.yaml`; extendable).
4. Ceramic capacitors: **C0G/NP0, X7R or X5R**, never Y5V/Z5U (C0G/NP0 added 2026-11-01: JLC's Basic small values are C0G, the better dielectric there).
5. Bulk adds show the full list for confirmation before anything is written.
6. **English datasheet preferred** within the same JLC tier (Basic/Preferred, or
   Extended); bilingual counts as English. A preference only: rule 1 comes first,
   and a part without one is still picked, with a note. (Mouser part number and
   datasheet as a second source: deferred until there is a Mouser API key.)

## Commits

Same style as the user's other repos (e.g. dev-tools):

- **Commit when the user asks**, and library content only after their OK on each add.
- **Short messages**: one subject line; a body only when the subject can't carry
  the point, then two lines at most. **No `Co-Authored-By` trailer.**
- The subject starts with the area it touches: `libkit:` (`tools/libkit/`,
  `tests/`), `parts:` (`parts/*.yaml` with the regenerated `symbols/` and
  tables), `lib:` (`schema/`, `src/symbols/`, `footprints/`, `3dmodels/`),
  `doc:` (README, CLAUDE.md, specs, plans), or `treewide:` when it spans
  several areas, e.g. `parts: E12 0402 1% resistors 1k–8.2k`.

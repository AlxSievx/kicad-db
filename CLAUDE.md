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
- `.libkit/` — local, not committed: the last bulk-add dry run, datasheet-language cache.

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
.venv\Scripts\python -m libkit refresh-stock      # re-query stock + JLC type of every part (network)
```

Only `jlc`, `bulk-add` (dry run) and `refresh-stock` use the network; transient
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
  `C0G,NP0,X7R,X5R`. Inductors are single-add only (no parametric source).
  Capacitors below 10pF are not needed (user decision): start series at 10p.
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

## Part naming

Names may only contain letters, digits and `_ - . + ,` (KLC G1.1). Write `%` as `pct`.

| Category | Pattern | Example |
|---|---|---|
| Capacitors | `C_<value w/o F>_<pkg>_<voltage>_<dielectric>` | `C_100n_0402_16V_X7R` |
| Resistors | `R_<value>_<pkg>_<tol>pct` | `R_10k_0402_1pct` |
| Inductors | `L_<value w/o H>_<pkg>_<current>` | `L_10u_0805_1A` |
| Everything else | the MPN | `TPS62130RGTR` |

Value notation (`value:` field): resistors `100R`, `4.7k`, `1M`; capacitors
`10pF`, `100nF`, `4.7uF`; inductors `10uH`. Other spellings are generated into
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

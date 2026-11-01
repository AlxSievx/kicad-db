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

## Commands (PowerShell, repo root)

```
.venv\Scripts\python -m libkit build        # regenerate symbols/ and the library tables
.venv\Scripts\python -m libkit check        # data, references, stale files, absolute paths, KLC
.venv\Scripts\python -m libkit fetch-klc    # once per clone: install the pinned KLC checker
.venv\Scripts\python -m libkit vendor-sym Device:C --into passives
.venv\Scripts\python -m libkit vendor-fp Capacitor_SMD:C_0402_1005Metric --family Passives_SMD
.venv\Scripts\python -m pytest
```

## Rules

- Run `build` and then `check` before every commit. `check` must report 0 errors.
- Commit library changes only after the user's OK on each add.
- Never rename or reuse a part name once it exists. To retire a part, set `status: deprecated`.
- Never write credentials or absolute paths anywhere. Every library path goes through `${LIB_DIR}`.
- Datasheets are links only. Use `https://www.lcsc.com/datasheet/<LCSC>.pdf`.
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
4. Ceramic capacitors: **X7R / X5R only**, never Y5V/Z5U.
5. Bulk adds show the full list for confirmation before anything is written.

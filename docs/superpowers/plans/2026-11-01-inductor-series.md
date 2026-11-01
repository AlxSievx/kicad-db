# Inductor Series Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `bulk-add` adds full series of chip ferrite beads (0402–1206) and SMD power inductors (one manufacturer series per size), so the Inductors library covers what the Altium library uses, with parts JLC actually stocks.

**Architecture:**
- **Beads** become a bulk kind. Candidates come from JLC's keyword search, filtered by `kind_of == "bead"`, package, and impedance at 100 MHz.
- **Bead values** follow a fixed impedance list (`FB` series: 30, 60, 120, 220, 330, 470, 600, 1000, 1500, 2200 Ω).
- **Bead pick:** best JLC tier, then the highest rated current (the bead analogue of "one voltage per value"), then the English datasheet preference, then stock.
- **Power inductors** become a bulk kind named by series. `bulk-add inductor --family SWPA4030S --series E6 --from 1u --to 470u` searches JLC for the family prefix. It keeps records whose MPN starts with it, and picks one part per inductance (best tier, then stock).
- **Inductor parts** are named by MPN, as CLAUDE.md requires for non-chip inductors.
- **Inductor footprints:** every part of one family shares one footprint, imported once with the existing single `add` (EasyEDA → normalised, `--fp-name L_Sunlord_SWPA4030S`, family `Inductor_SMD`).
- Both kinds reuse the dry run → table → `--write` flow and `pick_polar`'s pattern. A generic `pick_ranked(parts, key)` replaces the tantalum-only voltage key.

**Tech Stack:** Python 3.12, pytest, existing JLC search, easyeda2kicad import (`add`).

**Spec:** `docs/superpowers/specs/2026-11-01-kicad-library-design.md` (§6.4, §6.6, §6.7). Plan series: `docs/superpowers/plans/2026-11-01-library-foundation.md` (Plan 7).

## Findings that shaped this plan (probed 2026-11-01)

- **The Altium inductors are mostly not orderable at JLC any more.** Their LCSC numbers were checked live:
  - Coilcraft LPS3015 (19 values): stock 0–962 each, most below 100.
  - Würth WE-LHMI 74437321/324 (7 values): stock 0–24.
  - Würth ferrite beads 782633601 / 74479774222: stock 2 / 0.
  - The "WE 74404064" entries actually point at KOHERelec NRSC6045 substitutes (stock 75–10k).
  - Still fine: TDK ACP3225 / ACT1210 common-mode chokes (33k / 30k), SHOU HAN CY75-470UH (12k), YJYCOIN YPRH1209 (5k).
- **Sunlord SWPA** is the broadest stocked series at JLC per size, all Extended. Values with stock ≥ 1000 per size:

  | Series | Size | Values ≥ 1000 stock | Range |
  |---|---|---|---|
  | SWPA3015S | 3×3 | 15 | 1.2–150 µH |
  | SWPA4030S | 4×4 | 21 | 1–470 µH |
  | SWPA5040S | 5×5 | 15 | 2.2–1000 µH |
  | SWPA6045S | 6×6 | 25 | 1–470 µH |
  | SWPA8040S | 8×8 | 16 | — |

  cjiang FNR4030S/5040S/6045S have similar coverage; Taiyo Yuden NRS and Bourns SRN/SRP have thin stock. KiCad stock has no SWPA footprint (it has Sunlord MWSA only).
- **Ferrite beads** at JLC: 250–360 records per package. Basic ones: 0603 120 Ω Murata, 0603 600 Ω Sunlord, 0805 100 Ω / 600 Ω Sunlord. For one impedance, the current ratings range from 100 mA to 6 A.

## Decisions for the user to confirm (marked ⚑ in tasks)

1. ⚑ **Power inductor series:** Sunlord SWPA3015S (3×3), SWPA4030S (4×4), SWPA5040S (5×5), SWPA6045S (6×6), SWPA8040S (8×8), E6 values 1 µH–470 µH (1000 µH where stocked). They replace the Coilcraft LPS3015 and Würth LHMI series of the Altium library, which JLC no longer stocks.
2. ⚑ **Bead series per package 0402/0603/0805/1206:** 30, 60, 120, 220, 330, 470, 600, 1000, 1500, 2200 Ω at 100 MHz, one part per value, the highest current within the best tier.
3. ⚑ **Common-mode chokes and other Altium inductors with good stock** (TDK ACP3225-102-2P, ACT1210-510-2P, CY75-470UH, YPRH1209-101M) are added singly by C-number after the series, each shown for OK. The Würth WE-CNSW/WE-SL chokes and transformers without an LCSC number wait for "parts without LCSC".
4. ⚑ **Known manufacturers** gain `TAI-TECH`, `Chilisin` and `cjiang` (Changjiang Microelectronics; `cjiang (Changjiang…)`) for beads and inductors.

## Global Constraints

- All Global Constraints of Plans 1–6 hold (UTF-8 + LF, no absolute paths, names never renamed, stock only in YAML, `build` + `check` 0 errors before a commit, tests offline, network only in dry runs).
- Rules (spec §6.6): Basic/Preferred before Extended; stock ≥ ~1000 for bulk; known manufacturers only; English datasheet preferred within a tier.
- Naming (CLAUDE.md): chip beads `FB_<impedance>_<pkg>_<current>` with value `600R@100MHz`; non-chip inductors by MPN with value `10uH`.
- Commits: area prefix, short subject, at most two body lines, no Co-Authored-By trailer. Branch `plan7-inductor-series`, merged locally after the user's OK; library content only after the user's OK on each table.

## Review Focus

1. **Bead impedance at the wrong frequency.** `120Ω@1MHz` or `120Ω@100kHz` must not count as a 120 Ω@100 MHz bead. → Task 1 `test_bead_frequency_must_be_100mhz`.
2. **Current spellings.** `2A`, `2000mA`, `2.2A`, `-` and a missing rating must rank correctly or be rejected with a reason. → Task 1 `test_bead_current_order`.
3. **A family prefix that matches other series.** `SWPA4030S` must not take `SWPA4030S-HF` variants of other sizes or `SWPA40301S` look-alikes. The MPN must be the prefix followed by the inductance code. → Task 2 `test_family_prefix_exact`.
4. **A family whose footprint is not imported yet.** The dry run must refuse with the `add` command to run first, and must not write parts that point at a missing footprint. → Task 2 `test_family_requires_footprint`.
5. **Two parts with the same inductance in one family** (tolerance or packaging variants, `SWPA4030S100MT` vs `SWPA4030S100NT`): one row per value, the best tier then stock, with the other noted. → Task 2 `test_family_one_row_per_value`.

---

### Task 1: Bead bulk kind ⚑2 ⚑4

**Files:** Modify `tools/libkit/series.py` (`"FB"` list), `tools/libkit/pick.py` (`pick_ranked`), `tools/libkit/bulk.py`, `tools/libkit/__main__.py` (`bulk-add bead --package …`), `schema/library.yaml` (manufacturers). Create `tools/libkit/beads.py` (`candidates(value, package, search=None)`, `current_amps(text) -> float | None`). Fixtures: 6 bead records (two impedances × currents, one at 1 MHz, one with current `-`). Test: `tests/test_beads.py`.

- [ ] Failing tests: `test_bead_frequency_must_be_100mhz`, `test_bead_current_order` (Basic 200 mA beats Extended 2 A; among Extended 2 A beats 2000 mA tie by stock), `test_plan_bead_rows` (fake search; names `FB_600R_0603_500mA`), `test_write_bead_plan` (apply + `check(klc=False)` 0 errors).
- [ ] Implement; `pick_polar` re-expressed via `pick_ranked` (its tests stay green).
- [ ] `py -m pytest -q`; commit `libkit: bulk add for chip ferrite beads`.

### Task 2: Power-inductor family bulk ⚑1

**Files:** Create `tools/libkit/families.py` (`candidates(family, value, search=None)`, `family_footprint(root, family) -> str | None` = the footprint of an existing part whose MPN starts with the family, else `LIB_Inductor_SMD:L_<Brand>_<family>` when that file exists). Modify `bulk.py`, `__main__.py` (`bulk-add inductor --family X`; plan file `bulk-plan-inductor-<family>.json`). Test: `tests/test_families.py`.

- [ ] Failing tests: `test_family_prefix_exact`, `test_family_requires_footprint`, `test_family_one_row_per_value`, `test_family_entry` (name = MPN, value `10uH`, `current_rating`, `current_sat`, `dcr`, footprint from the family).
- [ ] Implement.
- [ ] `py -m pytest -q`; commit `libkit: bulk add for power-inductor families`.

### Task 3: Docs, review, content

- [ ] CLAUDE.md (commands, workflow: "import one family member with `add --fp-name L_Sunlord_<family>` first, then `bulk-add inductor --family`"), spec §6.6 note, plan series; commit `doc: inductor series`.
- [ ] One fresh reviewer over the branch; fixes; ask before merging.
- [ ] Content, each table for the user's OK:
  - **Footprints:** one `add` per family to import its footprint (5 adds, previews shown).
  - **Power inductors:** family dry runs.
  - **Beads:** dry runs for 0402, 0603, 0805, 1206.
  - **Singles:** the single adds of ⚑3.

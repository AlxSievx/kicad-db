# LIB — KiCad 10 part library

A personal KiCad 10 part library. Every part is a real, orderable part with
manufacturer, MPN and LCSC/JLC number, plus a symbol, footprint and 3D model.
The part data lives in YAML (`parts/`). The KiCad libraries are generated from
it and committed, so using the library needs nothing but KiCad.

## Use it in KiCad 10

1. Clone this repository, e.g. to `C:\kicad-db`.
2. **Preferences → Configure Paths:** add `LIB_DIR` pointing to the clone.
3. **Preferences → Manage Symbol Libraries:** add one entry with nickname
   `LIB`, library format **Table**, path `${LIB_DIR}/sym-lib-table`.
4. **Preferences → Manage Footprint Libraries:** add `LIB`, format **Table**,
   path `${LIB_DIR}/fp-lib-table`.
5. Restart KiCad.

The parts then appear as `LIB_Capacitors`, `LIB_Resistors`, … in the symbol
chooser. Search by value (`100n`, `0.1uF`), MPN or LCSC number (`C1525`).

## Work on it

Needs Python 3.12 and git.

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m pip install -e .
.venv\Scripts\python -m libkit fetch-klc

.venv\Scripts\python -m libkit build    # after editing parts/*.yaml
.venv\Scripts\python -m libkit check    # must report 0 errors before committing
.venv\Scripts\python -m pytest
```

How parts are named, picked and added is in [CLAUDE.md](CLAUDE.md).

## License

Base passive symbols, footprints and 3D models are derived from the KiCad
libraries (CC-BY-SA 4.0 with the KiCad library exception). See
[LICENSES/KiCad-libraries.md](LICENSES/KiCad-libraries.md).

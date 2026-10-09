# GR III fw 2.10 image-pipeline RE tools

Custom film looks (Kodak Ektar 100, Gold 200, Portra 400, Fujifilm Pro 400H, Kodak Vision3 250D) and RAW-NR changes
for the Ricoh GR III firmware 2.10, built by patching the official update file offline. Research notes: `FINDINGS.md`.

**Not included:** any Ricoh firmware, patched images or photos. You need your own `fwdc239b.bin` (2.10) and the
`gr4_editor` firmware container codec (expected at `../gr-custom-tool`). Flashing modified firmware can brick the camera;
use at your own risk. Not affiliated with or endorsed by Ricoh Imaging.

Film targets are rendered with [spektrafilm](https://github.com/andreavolpato/spektrafilm) LUTs (CC BY-SA 4.0 +
spektrafilm LUT license): the fitted curves/matrices in `work/**/fits` derive from them; credit spektrafilm, share alike.

License: code and notes MIT (`LICENSE`); the fit data in `work/**/fits` is derived from spektrafilm LUTs and stays
under their CC BY-SA 4.0 + LUT license terms.

Offline only. Input: `../fwdc239b.bin` (SHA-256 `d6a3c9c2…54bfd4`). Addresses are valid for this file only.

Setup (Python 3.12, needs gr-custom-tool's codec on disk):

```sh
python3 -m venv .venv && .venv/bin/pip install capstone numpy unicorn==2.1.4
mkdir -p work/fw
.venv/bin/python -I -c "
import sys; sys.path.insert(0,'../gr-custom-tool')
from gr4_editor.codec.container import inspect_container
from gr4_editor.codec.frames import decode_payload
d=open('../fwdc239b.bin','rb').read(); i=inspect_container(d)
dec,_=decode_payload(d[128:i['payload_end']], i['decoded_size'])
open('work/fw/rtos.bin','wb').write(dec[0x10870:0x10c5e30])"
```

| File | Purpose |
| --- | --- |
| `fw.py` | RTOS address helpers, xrefs (MOVW/MOVT, BL, literal), disassembly |
| `emu.py` | Unicorn harness (allocator/assert/log/SVC stubs) |
| `run_tuning.py` | Runs `ImageTuningStill::Make` for a given internal tone slot and returns the R2Y parameter block |
| `diffmodes.py`, `sens.py` | Diff R2Y output across modes / per image parameter |
| `cube_fit.py` | Fits .cube LUT(s) to look matrix + Cross Process curves (run in a venv with colour-science/scipy, e.g. spektrafilm's) |
| `make_film.py` | Writes a cube_fit result into Cross Process (own record + matrix + 9 curves) |
| `verify_film.py` | Offline checks + emulated R2Y diff of a make_film output vs stock |
| `make_films.py` | Four film modes over Cross Process / Vivid / Retro / HDR Tone (records, curves, selector code patch) + icons + names (FINDINGS §14) |
| `make_icons.py`, `make_names.py` | Redraw the mode icons in ICONBIN / rename the modes in all 21 UI languages (used by make_films) |
| `verify_films.py` | Offline checks of a make_films output (emulated still + LV, names, icons) |
| `make_ma_probe.py`, `make_ma_probe2.py`, `verify_ma_probe*.py`, `make_hue_chart.py` | MultiAxial probe firmwares (FINDINGS §15, §16) and their chart |
| `raw_nr.py` | RAW (PPU Bayer) noise reduction patches: off (`make_films.py --raw-nr-off`, §21) or only at ISO ≥ 6400 (`--raw-nr-from-6400`, §21b) / above a given ISO (`--raw-nr-above 8000`, §21c) |
| `raw_noise.py` | Measures noise correlation in DNGs to detect raw NR (FINDINGS §21) |
| `cca1.py`, `cca1_fit.py`, `verify_cca1.py` | Per-film post-gamma 3x3 (CCA1) warm-colour fix: fit, patch (`make_films.py --cca1`), emulated check (FINDINGS §22g) |
| `joint_fit.py` | Joint refit of look matrix + film curves + CCA1 for a film fit (films v9, FINDINGS §22i) |
| `make_films10.py`, `film_cave.py`, `armasm.py`, `verify_films10.py` | Films v10: five films (Bleach Bypass -> Vision3 250D, knot-stored curves), post-gamma 3x3 via the RGB->YCbCr matrix, emulated check (FINDINGS §22l; needs Homebrew llvm for llvm-mc) |
| `lab_fit.py` | Perceptual (dE2000) refit of a joint fit: look matrix + post matrix + curve corrections (films v11, FINDINGS §22m) |
| `make_cca1_probe.py` | Temporary v7 + red/blue swap in CCA1 (proved CCA1 is live) |
| `eval_warm.py` | Warm-hue (yellow/orange) vs overall error of film fits (films v3, FINDINGS §19) |
| `gr3patch.py` | Proof-of-concept builder: patches a look matrix and repacks a container (reuses stock frames) |

Only the §13 Portra build has been flashed and confirmed on a camera.

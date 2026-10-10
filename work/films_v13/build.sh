#!/bin/sh
# NOTE: make_slots.py now also draws per-film icons, so this produces the v13b file (work/films_v13b/build.sh).
# The flashed v13 file (SHA-256 6d4d6812...079a4bce) used the shared Positive Film icon.
# Films v13 (FINDINGS §24): stock modes + 6 film entries. Run from re-tools/ with a Python that has
# capstone/unicorn/numpy and gr-custom-tool on disk; PY overrides the interpreter.
set -e
PY=${PY:-python3}
F12=work/films_v12/fits
FILMS="portra=$F12/portra_b4n3_lab.json ektar=$F12/ektar_b1n3_lab.json gold=$F12/gold_b4n3_lab.json pro400h=$F12/pro400h_own_b4n3_lab.json vision3=work/films_v11/fits/vision3250d_2383_b4n3_lab.json classicneg=$F12/classicneg_b4n3_lab.json"
$PY make_slots.py --raw-nr-above 8000 work/films_v13/fwdc239b.bin $FILMS > work/films_v13/build.log
$PY verify_slots.py ../fwdc239b.bin work/films_v13/fwdc239b.bin $FILMS > work/films_v13/verify.log
tail -1 work/films_v13/verify.log

#!/bin/sh
# Films v15 (FINDINGS §26): v14 with the replacements in the movie list too (Cross curves freed, Cinema curves exact). v13c + Cinema (Yellow) / Cinema (Green) (GR IV) in place of Bleach Bypass / Retro and
# Kodak Vision3 500T (5219, on 2383 print) in place of Cross Process. Run from re-tools/ with a Python that has
# capstone/unicorn/numpy/PIL and gr-custom-tool on disk; PY overrides the interpreter.
set -e
PY=${PY:-python3}
F12=work/films_v12/fits
F14=work/films_v14/fits
FILMS="portra=$F12/portra_b4n3_lab.json ektar=$F12/ektar_b1n3_lab.json gold=$F12/gold_b4n3_lab.json pro400h=$F12/pro400h_own_b4n3_lab.json vision3=work/films_v11/fits/vision3250d_2383_b4n3_lab.json classicneg=$F12/classicneg_b4n3_lab.json cinema_yellow@18=$F14/cinema_yellow.json cinema_green@19=$F14/cinema_green.json vision3500t@21=$F14/vision3500t_2383_b4n3_lab.json"
$PY make_slots15.py --raw-nr-above 8000 work/films_v15/fwdc239b.bin $FILMS > work/films_v15/build.log
$PY verify_slots15.py ../fwdc239b.bin work/films_v15/fwdc239b.bin $FILMS > work/films_v15/verify.log
tail -1 work/films_v15/verify.log

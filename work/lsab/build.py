"""A/B test firmware: films v13c (make_slots.py) with Pro 400H / Vision3 250D swapped for the LUTSmith-method fits of
Portra 400 and Classic Neg (work/lsab/fit_ls.py). Menu: Portra 400, Portra 400 LS, Classic Neg, Classic Neg LS,
Ektar 100, Gold 200. Usage (from re-tools): work/lsab/build.py build|verify out.bin"""
import sys, json, runpy; sys.path.insert(0, '.')
import make_slots as M
from gr3patch import Image

M.FILMS.update(portra_ls='Portra LS', classicneg_ls='ClassicNeg LS')
M.ICON_LABELS.update(portra_ls=('LS400', (200, 150, 255)), classicneg_ls=('LS-NC', (240, 130, 210)))
F12 = 'work/films_v12/fits/'
FILMS = [('portra', F12 + 'portra_b4n3_lab.json'), ('portra_ls', 'work/lsab/portra_ls.json'),
         ('classicneg', F12 + 'classicneg_b4n3_lab.json'), ('classicneg_ls', 'work/lsab/classicneg_ls.json'),
         ('ektar', F12 + 'ektar_b1n3_lab.json'), ('gold', F12 + 'gold_b4n3_lab.json')]
cmd, out = sys.argv[1], sys.argv[2]
if cmd == 'build':
    img = Image(M.STOCK)
    info = M.patch(img, [(k, M.FILMS[k], json.load(open(p))) for k, p in FILMS], 8000)
    data, rep = img.build()
    open(out, 'wb').write(data)
    for k, v in info.items():
        print(k, v)
    print(rep)
else:
    sys.argv = ['verify_slots.py', M.STOCK, out] + [f'{k}={p}' for k, p in FILMS]
    runpy.run_path('verify_slots.py', run_name='__main__')

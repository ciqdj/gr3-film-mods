"""Sky of the A/B shots: camera JPG vs model (firmware look) vs film target, mean Lab / LCh over a sky box."""
import sys, json; sys.path.insert(0, '.'); sys.path.insert(0, 'work/lsab'); sys.path.insert(0, 'work/films_v8')
import numpy as np, cv2, colour
from scipy.optimize import least_squares
from cube_fit import model, target_of, de2000
from film_cave import knots_of, expand
import importlib.util
spec = importlib.util.spec_from_file_location('sheet', 'work/lsab/sheet.py'); sys.argv = ['x', '/dev/null']
src = open('work/lsab/sheet.py').read().split('rows = []')[0]; exec(src)
lab = lambda x: colour.XYZ_to_Lab(colour.sRGB_to_XYZ(np.clip(x, 0, 1)))
lch = lambda x: (lambda l: (l[0], np.hypot(l[1], l[2]), np.degrees(np.arctan2(l[2], l[1])) % 360))(lab(x))
SH = [('Portra ours', 'work/films_v12/fits/portra_b4n3_lab.json', 'R0011946'), ('Portra LS', 'work/lsab/portra_ls.json', 'R0011947'),
      ('ClassicNeg ours', 'work/films_v12/fits/classicneg_b4n3_lab.json', 'R0011948'), ('ClassicNeg LS', 'work/lsab/classicneg_ls.json', 'R0011949')]
print(f'{"":16s} {"sky box":>8s}  L / C / h   camera        model        target    | lin max  dE cam-mod mod-tgt')
for name, fp, n in SH:
    f = json.load(open(fp)); T = target_of(f['presets'][0])
    cv = [expand(knots_of(c)) for c in f['presets'][0]['curves']]; P = np.array(f['post_q512']) / 512
    look = lambda L: np.clip(model(np.array(f['matrix']), cv, L) @ P.T, 0, 1)
    lin = dng(n) @ EK.T * 0.18 / 7.8
    cam = jpg(n).astype(np.float32) / 255
    flat, cflat = lin.reshape(-1, 3), cam.reshape(-1, 3)
    use = (cflat.max(1) < 0.97) & (cflat.min(1) > 0.02)
    g = least_squares(lambda p: (look(flat[use] * np.exp(p[0])) - cflat[use]).ravel(), [0], loss='soft_l1', f_scale=0.05).x[0]
    box = (slice(5, 40), slice(380, 900))                     # sky, right of the towers (900x600 frame)
    L = lin[box].reshape(-1, 3) * np.exp(g)
    c, m, t = cam[box].reshape(-1, 3).mean(0), look(L).mean(0), np.clip(T(L), 0, 1).mean(0)
    s = lambda x: '%5.1f/%4.1f/%3.0f' % lch(x)
    print(f'{name:16s} {"":8s}  {s(c):>14s} {s(m):>14s} {s(t):>14s} | {L.max():.2f}  {de2000(c[None], m[None])[0]:5.2f} {de2000(m[None], t[None])[0]:5.2f}   gain {np.exp(g):.2f}')

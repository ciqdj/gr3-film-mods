"""Films v13 on camera (photo-v13): which look did the camera apply? EXIF ImageTone says Standard (256) for every
shot, so each JPG is compared against the Standard model and all six film models developed from its own DNG.
Same method as films_v12/check_v12.py (rawpy linear, ECC alignment, 375x250, EK from the photo-v10 Standard chart,
per-shot exposure gain + radial lens-shading gain fitted per model, edges / clipped pixels left out).
Usage (from re-tools): work/films_v13/check_v13.py"""
import sys, json, glob, os; sys.path.insert(0, '.'); sys.path.insert(0, 'work/films_v8')
import numpy as np, cv2, rawpy
from scipy.optimize import least_squares
from cube_fit import BASE, STD_LOOK, model, de2000
from chart import load
from film_cave import knots_of, expand
D10, D = '../photo-v10/', '../photo-v13/'
W, H = 375, 250

bg = lambda idx: np.interp(np.clip(idx, 0, 255), np.arange(256), BASE) / 16384
Js, Ls = load(D10 + 'R0011890')
lin0, std = Ls.reshape(-1, 3), Js.reshape(-1, 3)
ok = (std.max(1) < 0.95) & (std.min(1) > 0.03)
a = least_squares(lambda a: (bg(lin0[ok] @ a.reshape(3, 3).T) - std[ok]).ravel(), (STD_LOOK * 40).ravel()).x.reshape(3, 3)
EK = np.linalg.inv(STD_LOOK) @ a


def pair(n):
    with rawpy.imread(D + n + '.DNG') as r:
        lin = r.postprocess(use_camera_wb=True, output_color=rawpy.ColorSpace.sRGB, gamma=(1, 1), no_auto_bright=True,
                            output_bps=16, half_size=True, user_flip=0).astype(np.float32) / 65535
    jpg = cv2.cvtColor(cv2.imread(D + n + '.JPG'), cv2.COLOR_BGR2RGB).astype(np.float32) / 255
    h, w = lin.shape[:2]; y0, x0 = (h - 2000) // 2, (w - 3000) // 2
    lin = lin[y0:y0 + 2000, x0:x0 + 3000]
    jl = cv2.resize(jpg, (3000, 2000), interpolation=cv2.INTER_AREA)
    s = lambda g: cv2.resize(g, (750, 500), interpolation=cv2.INTER_AREA).astype(np.float32)
    warp = np.eye(2, 3, dtype=np.float32)
    cc, warp = cv2.findTransformECC(s(lin.mean(2) ** (1 / 2.2)), s(jl.mean(2)), warp, cv2.MOTION_AFFINE,
                                    (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 200, 1e-6), None, 5)
    warp[:, 2] *= 4
    jl = cv2.warpAffine(jl, warp, (3000, 2000), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP)
    small = lambda x: cv2.resize(x, (W, H), interpolation=cv2.INTER_AREA)
    js = small(jl)
    g = js.mean(2)
    grad = np.hypot(cv2.Sobel(g, cv2.CV_32F, 1, 0), cv2.Sobel(g, cv2.CV_32F, 0, 1))
    flat = cv2.dilate((grad > 0.15).astype(np.uint8), np.ones((3, 3))) == 0
    flat[:4], flat[-4:], flat[:, :4], flat[:, -4:] = False, False, False, False
    return small(lin).reshape(-1, 3), js.reshape(-1, 3), flat.ravel(), cc


def film(fp):
    f = json.load(open(fp))
    cv = [expand(knots_of(c)) for c in f['presets'][0]['curves']]          # v13: every film as knots
    P = np.array(f.get('post_q512', f.get('cca1_q512'))) / 512
    return lambda L: np.clip(model(np.array(f['matrix']), cv, L) @ P.T, 0, 1)


ident = np.minimum(np.arange(256) * 64.0, 16383)
LOOKS = {'Standard': lambda L: np.clip(model(STD_LOOK, [ident] * 3, L), 0, 1)}
F12, F11 = 'work/films_v12/fits/', 'work/films_v11/fits/'
for name, fp in (('Portra 400', F12 + 'portra_b4n3_lab.json'), ('Ektar 100', F12 + 'ektar_b1n3_lab.json'),
                 ('Gold 200', F12 + 'gold_b4n3_lab.json'), ('Pro 400H', F12 + 'pro400h_own_b4n3_lab.json'),
                 ('Vision3 250D', F11 + 'vision3250d_2383_b4n3_lab.json'), ('Classic Neg', F12 + 'classicneg_b4n3_lab.json')):
    LOOKS[name] = film(fp)

yy, xx = np.mgrid[0:H, 0:W]
r2 = (((xx - W / 2 + 0.5) ** 2 + (yy - H / 2 + 0.5) ** 2) / ((W / 2) ** 2 + (H / 2) ** 2)).ravel()
shots = sorted(os.path.basename(p)[:-4] for p in glob.glob(D + '*.DNG'))
print('mean dE2000 camera JPG vs each look (exposure + lens-shading gain fitted per look); best marked *')
print(f'{"shot":9s} ' + ' '.join(f'{k[:12]:>12s}' for k in LOOKS))
for n in shots:
    lin, cam, flat, cc = pair(n)
    L0 = lin @ EK.T * 0.18 / 7.8
    use = flat & (cam.max(1) < 0.97) & (cam.min(1) > 0.02) & (lin.max(1) < 0.9)
    res = {}
    for k, f in LOOKS.items():
        Lp = lambda p: L0 * (np.exp(p[0]) * (1 + p[1] * r2 + p[2] * r2 ** 2))[:, None]
        p = least_squares(lambda p: (f(Lp(p)[use]) - cam[use]).ravel(), [0, 0, 0], loss='soft_l1', f_scale=0.05).x
        res[k] = de2000(cam, f(Lp(p)))[use].mean()
    best = min(res, key=res.get)
    print(f'{n:9s} ' + ' '.join(f'{v:11.2f}{"*" if k == best else " "}' for k, v in res.items()) + f'  (ECC {cc:.3f})')

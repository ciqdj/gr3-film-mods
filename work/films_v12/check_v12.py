"""Films v12 on camera (photo-v12): one night scene, R0011928 (captured as Cross) and in-camera RAW developments of its DNG
in every film mode (R0011929-33). Camera JPG vs v12 model vs target (spektrafilm / Classic Neg cube), per pixel.
Shot with Multi Auto WB, DR expansion Auto and shadow correction on (not the chart settings), ISO 2500.
Same method as films_v11/check_v11.py:
DNG developed linear (rawpy, camera WB, sRGB primaries, half size), JPG aligned to it by ECC, both 375x250. Raw ->
look input = EK from the photo-v10 Standard chart shot (as check_v10.py). Per shot an exposure gain and a radial gain
(1 + a r^2 + b r^4, the in-camera lens shading correction) are fitted against the v11 model; the target is computed
from the same corrected input. Edges (high local gradient) and clipped/near-black pixels are left out.
Usage (from re-tools): work/films_v12/check_v12.py"""
import sys, json; sys.path.insert(0, '.'); sys.path.insert(0, 'work/films_v8')
import numpy as np, cv2, rawpy
from scipy.optimize import least_squares
from cube_fit import BASE, STD_LOOK, target_of, model, de2000
from chart import load
from film_cave import knots_of, expand
D10, D, RAW = '../photo-v10/', '../photo-v12/', 'R0011928'
W, H = 375, 250

# raw -> look input, from the v10 Standard chart shot
bg = lambda idx: np.interp(np.clip(idx, 0, 255), np.arange(256), BASE) / 16384
Js, Ls = load(D10 + 'R0011890')
lin0, std = Ls.reshape(-1, 3), Js.reshape(-1, 3)
ok = (std.max(1) < 0.95) & (std.min(1) > 0.03)
a = least_squares(lambda a: (bg(lin0[ok] @ a.reshape(3, 3).T) - std[ok]).ravel(), (STD_LOOK * 40).ravel()).x.reshape(3, 3)
EK = np.linalg.inv(STD_LOOK) @ a


def pair(n):
    with rawpy.imread(D + RAW + '.DNG') as r:
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


def look(fp):
    f = json.load(open(fp))
    cv = [np.array(c) for c in f['presets'][0]['curves']]
    if 'vision3' in fp or 'classicneg' in fp:
        cv = [expand(knots_of(c)) for c in cv]
    P = np.array(f.get('post_q512', f.get('cca1_q512'))) / 512
    return lambda L: np.clip(model(np.array(f['matrix']), cv, L) @ P.T, 0, 1), f['presets'][0]


yy, xx = np.mgrid[0:H, 0:W]
r2 = (((xx - W / 2 + 0.5) ** 2 + (yy - H / 2 + 0.5) ** 2) / ((W / 2) ** 2 + (H / 2) ** 2)).ravel()
F = 'work/films_v12/fits/'
films = [('R0011928', 'Portra 400 (Cross, capture)', 'portra_b4n3'), ('R0011929', 'Portra 400 (Cross, RAW dev)', 'portra_b4n3'),
         ('R0011930', 'Pro 400H (HDR)', 'pro400h_own_b4n3'), ('R0011931', 'Gold 200 (Retro)', 'gold_b4n3'),
         ('R0011932', 'Classic Neg (Bleach)', 'classicneg_b4n3'), ('R0011933', 'Ektar 100 (Vivid)', 'ektar_b1n3')]
print(f'{"shot":9s} {"film":28s} {"px":>5s} {"gain":>5s} {"shade r=1":>9s} | {"cam-model":>9s} {"cam-target":>10s} {"model-tgt":>9s}')
for n, name, stem in films:
    lin, cam, flat, cc = pair(n)
    m11, preset = look(F + stem + '_lab.json')
    tgt = target_of(preset)
    L0 = lin @ EK.T * 0.18 / 7.8
    use0 = flat & (cam.max(1) < 0.97) & (cam.min(1) > 0.02) & (lin.max(1) < 0.9)
    Lp = lambda p: L0 * (np.exp(p[0]) * (1 + p[1] * r2 + p[2] * r2 ** 2))[:, None]
    p = least_squares(lambda p: (m11(Lp(p)[use0]) - cam[use0]).ravel(), [0, 0, 0], loss='soft_l1', f_scale=0.05).x
    L = Lp(p)
    mo, t = m11(L), tgt(L)
    use = use0 & (t.min(1) > 0.02) & (t.max(1) < 0.98)
    e = lambda x, y: de2000(x, y)[use].mean()
    print(f'{n:9s} {name:28s} {use.sum():5d} {np.exp(p[0]):5.2f} {1 + p[1] + p[2]:9.2f} | {e(cam, mo):9.2f} '
          f'{e(cam, t):10.2f} {e(mo, t):9.2f}   (ECC {cc:.3f})')

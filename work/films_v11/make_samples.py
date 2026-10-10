"""Sample images for films v11 (written without EXIF, so no camera serial).
  camera_grid.jpg   real in-camera JPEGs of the same scene (photo-v11, handheld, aligned to R0011905 by ECC)
  sim_grid_<n>.jpg  one DNG rendered through the v11 model of every film, plus Standard (camera-vs-model ~0.9 dE)
  sim_<n>_<film>.jpg the same, one file per look
  sf_grid_<n>.jpg   the same DNG through spektrafilm itself (the fit target), sf_<n>_<film>.jpg per film
  vs_grid_<n>.jpg   per film: v11 model (left) next to spektrafilm (right)
Usage (from re-tools): work/films_v11/make_samples.py out_dir"""
import sys, os, json; sys.path.insert(0, '.'); sys.path.insert(0, 'work/films_v8')
import numpy as np, cv2, rawpy
from scipy.optimize import least_squares
from cube_fit import BASE, STD_LOOK, model, load_target
from chart import load
from film_cave import knots_of, expand
D10, D, F11 = '../photo-v10/', '../photo-v11/', 'work/films_v11/fits/'
OUT = sys.argv[1]; os.makedirs(OUT, exist_ok=True)
FILMS = [('Ektar 100', 'ektar_b1n3', 'R0011905'), ('Gold 200', 'gold_b4n3', 'R0011901'),
         ('Pro 400H', 'pro400h_own_b4n3', 'R0011900'), ('Portra 400', 'portra_b4n3', 'R0011898'),
         ('Vision3 250D', 'vision3250d_2383_b4n3', 'R0011902')]

bg = lambda idx: np.interp(np.clip(idx, 0, 255), np.arange(256), BASE) / 16384
Js, Ls = load(D10 + 'R0011890')
lin0, std = Ls.reshape(-1, 3), Js.reshape(-1, 3)
ok = (std.max(1) < 0.95) & (std.min(1) > 0.03)
A = least_squares(lambda a: (bg(lin0[ok] @ a.reshape(3, 3).T) - std[ok]).ravel(), (STD_LOOK * 40).ravel()).x.reshape(3, 3)
EK = np.linalg.inv(STD_LOOK) @ A


def look(stem):
    f = json.load(open(F11 + stem + '_lab.json'))
    cv = [np.array(c) for c in f['presets'][0]['curves']]
    if 'vision3' in stem:
        cv = [expand(knots_of(c)) for c in cv]
    P = np.array(f['post_q512']) / 512
    return lambda L: np.clip(model(np.array(f['matrix']), cv, L) @ P.T, 0, 1), load_target(f['presets'][0]['spec'], 'vlog', 0)


def label(img, text):
    h = img.shape[0]
    s = h / 900
    cv2.putText(img, text, (int(24 * s), int(h - 28 * s)), cv2.FONT_HERSHEY_SIMPLEX, 1.6 * s, (0, 0, 0), int(7 * s), cv2.LINE_AA)
    cv2.putText(img, text, (int(24 * s), int(h - 28 * s)), cv2.FONT_HERSHEY_SIMPLEX, 1.6 * s, (255, 255, 255), int(3 * s), cv2.LINE_AA)
    return img


def grid(tiles, cols=3):
    h, w = tiles[0].shape[:2]
    tiles = tiles + [np.full((h, w, 3), 255, np.uint8)] * (-len(tiles) % cols)
    return np.vstack([np.hstack(tiles[i:i + cols]) for i in range(0, len(tiles), cols)])


save = lambda name, rgb: cv2.imwrite(os.path.join(OUT, name), cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 92])
u8 = lambda x: (np.clip(x, 0, 1) * 255 + 0.5).astype(np.uint8)

# 1. real camera JPEGs, aligned to the first
TW, TH = 1200, 800
jp = lambda n: cv2.cvtColor(cv2.imread(D + n + '.JPG'), cv2.COLOR_BGR2RGB)
ref = cv2.resize(jp(FILMS[0][2]), (TW, TH), interpolation=cv2.INTER_AREA)
g = lambda im: cv2.resize(cv2.cvtColor(im, cv2.COLOR_RGB2GRAY), (600, 400), interpolation=cv2.INTER_AREA).astype(np.float32) / 255
tiles = []
for name, _, n in FILMS:
    im = cv2.resize(jp(n), (TW, TH), interpolation=cv2.INTER_AREA)
    warp = np.eye(3, dtype=np.float32)
    _, warp = cv2.findTransformECC(g(ref), g(im), warp, cv2.MOTION_HOMOGRAPHY,
                                   (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 200, 1e-6), None, 5)
    S = np.diag([2, 2, 1]).astype(np.float32)
    im = cv2.warpPerspective(im, S @ warp @ np.linalg.inv(S), (TW, TH), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP)
    tiles.append(label(im[24:-24, 36:-36].copy(), name + ' (camera)'))
save('camera_grid.jpg', grid(tiles))

# 2. one DNG through every look
for n, gain in (('R0011905', 1.04), ('R0011906', 0.99)):
    with rawpy.imread(D + n + '.DNG') as r:
        lin = r.postprocess(use_camera_wb=True, output_color=rawpy.ColorSpace.sRGB, gamma=(1, 1), no_auto_bright=True,
                            output_bps=16, half_size=True, user_flip=0).astype(np.float32) / 65535
    h, w = lin.shape[:2]; y0, x0 = (h - 2000) // 2, (w - 3000) // 2
    lin = cv2.resize(lin[y0:y0 + 2000, x0:x0 + 3000], (1800, 1200), interpolation=cv2.INTER_AREA)
    flat = lin.reshape(-1, 3)
    L = flat @ EK.T * 0.18 / 7.8 * gain
    sims = [(name, look(stem)) for name, stem, _ in FILMS]
    out = [('Standard', bg(flat @ A.T * gain))] + [(name, m(L)) for name, (m, _) in sims]
    sf = [(name, np.clip(t(L), 0, 1)) for name, (_, t) in sims]
    tiles, sft, vs = [], [], []
    for name, x in out:
        im = u8(x.reshape(1200, 1800, 3))
        save(f'sim_{n}_{name.replace(" ", "_")}.jpg', im)
        tiles.append(label(cv2.resize(im, (TW, TH), interpolation=cv2.INTER_AREA), name))
    for (name, x), (_, y) in zip(sf, out[1:]):
        im = u8(x.reshape(1200, 1800, 3))
        save(f'sf_{n}_{name.replace(" ", "_")}.jpg', im)
        sft.append(label(cv2.resize(im, (TW, TH), interpolation=cv2.INTER_AREA), name + ' (spektrafilm)'))
        vs += [label(cv2.resize(u8(y.reshape(1200, 1800, 3)), (TW, TH), interpolation=cv2.INTER_AREA), name + ' (GR III v11)'), sft[-1]]
    save(f'sim_grid_{n}.jpg', grid(tiles))
    save(f'sf_grid_{n}.jpg', grid(sft))
    save(f'vs_grid_{n}.jpg', grid(vs, cols=2))
print(sorted(os.listdir(OUT)))

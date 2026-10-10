"""Films v12 samples: one photo-v11 DNG through Standard, Vision3 250D (v11), the v12 Classic Neg model and the Classic Neg
cube itself (the fit target), plus side by side model/cube. Written without EXIF (cv2), so no camera serial.
Usage (from re-tools): work/films_v12/make_samples.py out_dir"""
import sys, os, json; sys.path.insert(0, '.'); sys.path.insert(0, 'work/films_v8')
import numpy as np, cv2, rawpy
from scipy.optimize import least_squares
from cube_fit import BASE, STD_LOOK, model, target_of
from chart import load
from film_cave import knots_of, expand
D10, D = '../photo-v10/', '../photo-v11/'
OUT = sys.argv[1]; os.makedirs(OUT, exist_ok=True)

bg = lambda idx: np.interp(np.clip(idx, 0, 255), np.arange(256), BASE) / 16384
Js, Ls = load(D10 + 'R0011890')
lin0, std = Ls.reshape(-1, 3), Js.reshape(-1, 3)
ok = (std.max(1) < 0.95) & (std.min(1) > 0.03)
A = least_squares(lambda a: (bg(lin0[ok] @ a.reshape(3, 3).T) - std[ok]).ravel(), (STD_LOOK * 40).ravel()).x.reshape(3, 3)
EK = np.linalg.inv(STD_LOOK) @ A


def look(fp):
    f = json.load(open(fp))
    cv = [expand(knots_of(c)) for c in f['presets'][0]['curves']]      # Bleach slot: knot tables
    P = np.array(f['post_q512']) / 512
    return lambda L: np.clip(model(np.array(f['matrix']), cv, L) @ P.T, 0, 1), target_of(f['presets'][0])


def label(img, text):
    s = img.shape[0] / 900
    for col, th in (((0, 0, 0), 7), ((255, 255, 255), 3)):
        cv2.putText(img, text, (int(24 * s), int(img.shape[0] - 28 * s)), cv2.FONT_HERSHEY_SIMPLEX, 1.6 * s, col,
                    int(th * s), cv2.LINE_AA)
    return img


save = lambda name, rgb: cv2.imwrite(os.path.join(OUT, name), cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 92])
u8 = lambda x: (np.clip(x, 0, 1) * 255 + 0.5).astype(np.uint8)
v250, _ = look('work/films_v11/fits/vision3250d_2383_b4n3_lab.json')
nc, nc_t = look('work/films_v12/fits/classicneg_b4n3_lab.json')
TW, TH = 1200, 800
for n, gain in (('R0011905', 1.04), ('R0011906', 0.99), ('R0011898', 1.0), ('R0011901', 1.07)):
    with rawpy.imread(D + n + '.DNG') as r:
        lin = r.postprocess(use_camera_wb=True, output_color=rawpy.ColorSpace.sRGB, gamma=(1, 1), no_auto_bright=True,
                            output_bps=16, half_size=True, user_flip=0).astype(np.float32) / 65535
    h, w = lin.shape[:2]; y0, x0 = (h - 2000) // 2, (w - 3000) // 2
    flat = cv2.resize(lin[y0:y0 + 2000, x0:x0 + 3000], (1800, 1200), interpolation=cv2.INTER_AREA).reshape(-1, 3)
    L = flat @ EK.T * 0.18 / 7.8 * gain
    out = [('Standard', bg(flat @ A.T * gain)), ('Vision3 250D (v11)', v250(L)), ('Classic Neg (GR III v12)', nc(L)),
           ('Classic Neg (cube)', nc_t(L))]
    tiles = []
    for name, x in out:
        im = u8(x.reshape(1200, 1800, 3))
        save(f'{n}_{name.split(" (")[0].replace(" ", "_")}{"_cube" if "cube" in name else ""}.jpg', im)
        tiles.append(label(cv2.resize(im, (TW, TH), interpolation=cv2.INTER_AREA), name))
    save(f'grid_{n}.jpg', np.vstack([np.hstack(tiles[:2]), np.hstack(tiles[2:])]))
print(sorted(os.listdir(OUT)))

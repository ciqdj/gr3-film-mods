"""Comparison sheet (no EXIF): per film, camera JPG ours | camera JPG LUTSmith-method | film target from the DNG.
Usage (from re-tools): work/lsab/sheet.py out.jpg"""
import sys, json; sys.path.insert(0, '.'); sys.path.insert(0, 'work/films_v8')
import numpy as np, cv2, rawpy
from scipy.optimize import least_squares
from cube_fit import BASE, STD_LOOK, model, target_of
from chart import load
from film_cave import knots_of, expand
D = '../photo-lsab/'
bg = lambda idx: np.interp(np.clip(idx, 0, 255), np.arange(256), BASE) / 16384
Js, Ls = load('../photo-v10/R0011890')
lin0, std = Ls.reshape(-1, 3), Js.reshape(-1, 3)
ok = (std.max(1) < 0.95) & (std.min(1) > 0.03)
A = least_squares(lambda a: (bg(lin0[ok] @ a.reshape(3, 3).T) - std[ok]).ravel(), (STD_LOOK * 40).ravel()).x.reshape(3, 3)
EK = np.linalg.inv(STD_LOOK) @ A
TW, TH = 900, 600
ROWS = [('Portra 400', 'work/films_v12/fits/portra_b4n3_lab.json', 'R0011946', 'R0011947'),
        ('Classic Neg', 'work/films_v12/fits/classicneg_b4n3_lab.json', 'R0011948', 'R0011949')]


def label(img, text):
    s = img.shape[0] / 900
    for col, th in (((0, 0, 0), 7), ((255, 255, 255), 3)):
        cv2.putText(img, text, (int(24 * s), int(img.shape[0] - 28 * s)), cv2.FONT_HERSHEY_SIMPLEX, 1.6 * s, col, max(1, int(th * s)), cv2.LINE_AA)
    return img


def dng(n):
    with rawpy.imread(D + n + '.DNG') as r:
        lin = r.postprocess(use_camera_wb=True, output_color=rawpy.ColorSpace.sRGB, gamma=(1, 1), no_auto_bright=True,
                            output_bps=16, half_size=True, user_flip=0).astype(np.float32) / 65535
    h, w = lin.shape[:2]; y0, x0 = (h - 2000) // 2, (w - 3000) // 2
    return cv2.resize(lin[y0:y0 + 2000, x0:x0 + 3000], (TW, TH), interpolation=cv2.INTER_AREA)


def jpg(n):
    im = cv2.cvtColor(cv2.imread(D + n + '.JPG'), cv2.COLOR_BGR2RGB)
    h, w = im.shape[:2]; y0, x0 = (h - 4000) // 2, (w - 6000) // 2
    return cv2.resize(im[max(y0, 0):max(y0, 0) + 4000, max(x0, 0):max(x0, 0) + 6000], (TW, TH), interpolation=cv2.INTER_AREA)


rows = []
for name, fp, n_ours, n_ls in ROWS:
    f = json.load(open(fp)); T = target_of(f['presets'][0])
    cv = [expand(knots_of(c)) for c in f['presets'][0]['curves']]
    P = np.array(f['post_q512']) / 512
    lin = dng(n_ours).reshape(-1, 3) @ EK.T * 0.18 / 7.8
    cam = jpg(n_ours).reshape(-1, 3).astype(np.float32) / 255
    use = (cam.max(1) < 0.97) & (cam.min(1) > 0.02)
    g = least_squares(lambda p: (np.clip(model(np.array(f['matrix']), cv, lin[use] * np.exp(p[0])) @ P.T, 0, 1) - cam[use]).ravel(), [0], loss='soft_l1', f_scale=0.05).x[0]
    tgt = (np.clip(T(lin * np.exp(g)), 0, 1).reshape(TH, TW, 3) * 255 + 0.5).astype(np.uint8)
    rows.append(np.hstack([label(jpg(n_ours), f'{name}: ours (camera)'), label(jpg(n_ls), f'{name}: LUTSmith (camera)'),
                           label(tgt, f'{name}: film target')]))
cv2.imwrite(sys.argv[1], cv2.cvtColor(np.vstack(rows), cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 92])

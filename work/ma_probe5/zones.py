"""Probe 5 hue chart (photo-ma6 R0011959 Negative = MultiAxial off, R0011960 Positive = GR IV set + marker matrices):
per patch gain Positive/Negative in the linear (base-gamma index) domain -> marker zone. Chart = make_hue_chart.py
(36 hues x 6 sat/val rows + grey row, 3840x2160 geometry). Usage (from re-tools): work/ma_probe5/zones.py"""
import sys, colorsys; sys.path.insert(0, '.')
import numpy as np, cv2
from cube_fit import BASE
from make_ma_probe5 import MARK
D = '../photo-ma6/'
W, H = 3840, 2160
m = int(H * 0.06)
MK = np.float32([[m // 2 + m / 2, m // 2 + m / 2], [W - m * 3 // 2 + m / 2, m // 2 + m / 2],
                 [m // 2 + m / 2, H - m * 3 // 2 + m / 2], [W - m * 3 // 2 + m / 2, H - m * 3 // 2 + m / 2]])
gx0, gy0, gx1, gy1 = m * 2, m * 2, W - m * 2, H - m * 2
ROWS = [(1.0, 1.0), (0.6, 1.0), (0.3, 1.0), (1.0, 0.55), (0.6, 0.55), (0.3, 0.55)]
cw, ch = (gx1 - gx0) / 36, (gy1 - gy0) / 7


def markers(img):
    g = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    n, lab, st, cen = cv2.connectedComponentsWithStats((g > 150).astype(np.uint8))
    c = []
    for i in range(1, n):
        x, y, w, h, a = st[i]
        if 2000 < a < 200000 and 0.75 < w / h < 1.33 and a > 0.8 * w * h:
            ring = g[max(0, y - h // 2):y + h + h // 2, max(0, x - w // 2):x + w + w // 2]
            if np.median(ring) < 90:
                c.append(cen[i])
    c = np.array(c)
    assert len(c) == 4, c
    s = c[np.argsort(c[:, 1])]
    top, bot = s[:2][np.argsort(s[:2, 0])], s[2:][np.argsort(s[2:, 0])]
    return np.float32([top[0], top[1], bot[0], bot[1]])


def patches(path, Hm=None):
    img = cv2.cvtColor(cv2.imread(path), cv2.COLOR_BGR2RGB).astype(np.float32) / 255
    if Hm is None:                       # markers found on the Negative shot; Positive (speckled markers) reuses them
        Hm = cv2.getPerspectiveTransform(MK, markers((img * 255).astype(np.uint8)))
    out, sd = np.zeros((7, 36, 3)), np.zeros((7, 36))
    for r in range(7):
        for c in range(36):
            cx, cy = gx0 + (c + 0.5) * cw, gy0 + (r + 0.5) * ch
            q = np.float32([[cx + dx * cw * 0.3, cy + dy * ch * 0.3] for dx in (-1, 1) for dy in (-1, 1)])
            p = cv2.perspectiveTransform(q[None], Hm)[0]
            x0, y0 = p.min(0).astype(int); x1, y1 = p.max(0).astype(int)
            patch = img[y0:y1, x0:x1].reshape(-1, 3)
            out[r, c] = patch.mean(0); sd[r, c] = patch.mean(1).std()
    return out, sd, Hm


idx = lambda y: np.interp(np.clip(y, 0, 1) * 16384, BASE, np.arange(256))   # JPG value -> linear index (Standard)
neg, sn, Hm = patches(D + 'R0011959.JPG')
pos, sp, _ = patches(D + 'R0011960.JPG', Hm)        # tripod: same framing (checked below on the grey row)
gain = idx(pos).sum(2) / np.maximum(idx(neg).sum(2), 1e-3)
zone_of = lambda g: int(np.argmin([abs(g - v) for v in MARK[:6]]))
names = ['s1 v1', 's.6 v1', 's.3 v1', 's1 v.55', 's.6 v.55', 's.3 v.55', 'grey']
print('gain Positive/Negative per patch (linear); hue of column c = 10*c deg (HSV)')
print('row      ' + ' '.join(f'{10 * c:4d}' for c in range(36)))
for r in range(7):
    print(f'{names[r]:8s} ' + ' '.join(f'{gain[r, c]:4.2f}' for c in range(36)))
print('speckle (patch SD Positive - Negative, x100)')
for r in range(7):
    print(f'{names[r]:8s} ' + ' '.join(f'{100 * (sp[r, c] - sn[r, c]):4.1f}' for c in range(36)))
np.savez('work/ma_probe5/zones.npz', neg=neg, pos=pos, gain=gain, sp=sp, sn=sn)

# --- geometry check against GR4-LUTSmith's GR IV hue sectors (12 sectors in the Cb/Cr angle of the linear signal
# after the look matrix; sector g uses matrix 5g..5g+4). z = Negative patch in linear index units (MultiAxial input).
import importlib.util
spec = importlib.util.spec_from_file_location('ls', sys.argv[1] + '/gr4_lutsmith.py') if len(sys.argv) > 1 else None
if spec:
    ls = importlib.util.module_from_spec(spec); spec.loader.exec_module(ls)
    z = idx(neg).reshape(-1, 3)
    g, _, _ = ls.hue_coords(z, ls.HUE_BOUNDS)
    S = np.array(ls.HUE_YCC, float) / 256; ycc = z @ S.T
    ang = np.degrees(np.arctan2(ycc[:, 2], ycc[:, 1])) % 360; chroma = np.hypot(ycc[:, 1], ycc[:, 2])
    pred = np.array(MARK)[g]; obs = gain.ravel()
    col = slice(0, 6 * 36)                                   # coloured rows only
    err = np.abs(obs - pred)[col]; ok = err < 0.06
    print(f'\nLUTSmith sectors predict the marker gain on {ok.sum()}/{ok.size} coloured patches (|err| < 0.06)')
    o = np.argsort(ang[col])
    print('sorted by Cb/Cr angle: angle sector pred obs (misses only)')
    for i in o:
        if not ok[i]:
            print(f'  {ang[i]:6.1f}  g{g[i]:2d}  {pred[i]:.2f}  {obs[i]:.2f}  chroma {chroma[i]:5.1f}  row {i // 36} hue {10 * (i % 36)}')
    # darker / desaturated rows read compressed gains (monitor flare, black offset): per row fit obs = a + b * pred on
    # the patches LUTSmith's geometry already explains, then classify every patch by the nearest corrected marker
    fixed = obs.copy()
    for r in range(6):
        s_ = slice(36 * r, 36 * r + 36); k = np.abs(obs[s_] - pred[s_]) < 0.12
        b, a = np.polyfit(pred[s_][k], obs[s_][k], 1); fixed[s_] = (obs[s_] - a) / b
        print(f'  row {r}: obs = {a:+.2f} + {b:.2f} * marker')
    marks = np.array(MARK[:6]); near = marks[np.argmin(np.abs(fixed[:, None] - marks[None]), 1)]
    hit = (near == pred)[col]
    print(f'after the per-row correction: {hit.sum()}/{hit.size} coloured patches land in the predicted sector')
    for i in np.argsort(ang[col]):
        if not hit[i]:
            gb = ang[i] - np.array(ls.HUE_BOUNDS); gb = (gb + 180) % 360 - 180
            print(f'  miss: angle {ang[i]:6.1f} (nearest bound {gb[np.argmin(np.abs(gb))]:+.1f} deg) sector g{g[i]} '
                  f'pred {pred[i]:.2f} corrected obs {fixed[i]:.2f} chroma {chroma[i]:4.1f} row {i // 36} hue {10 * (i % 36)}')
    dist = np.min(np.abs((ang[:, None] - np.array(ls.HUE_BOUNDS)[None] + 180) % 360 - 180), 1)
    for cmin in (0, 4):
        sel = (dist > 3)[col] & (chroma[col] >= cmin)
        e = np.abs(fixed[col] - pred[col])[sel]
        print(f'patches > 3 deg from a sector edge, chroma >= {cmin}: {sel.sum()}, |corrected - marker| < 0.10 on '
              f'{(e < 0.10).sum()}, median {np.median(e):.3f}, corr {np.corrcoef(fixed[col][sel], pred[col][sel])[0, 1]:.3f}')

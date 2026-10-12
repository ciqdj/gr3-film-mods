#!/usr/bin/env python3
"""Black-box simulator of the a7C II colour/tone pipeline: RAW in -> camera JPEG out.

The camera is treated as an unknown function of the scene colour.  Every training ARW already carries the
camera's own rendering (the full-size JpgFromRaw, 7008x4672, same look/WB/DRO as the JPEG/HEIF), so one
ARW = one (input, output) pair.  We:

  1. develop the RAW to a fixed, camera-independent input space  (scene-linear Rec.2020, D65, as-shot WB),
  2. register the camera JPEG onto it (the JPEG is lens-corrected: scale + radial distortion + shift),
  3. sample flat, unclipped pixels and fit one regularised 3D LUT  log2(input) -> sRGB-encoded output,
  4. render any RAW (a7C II ARW or GR III DNG) through that LUT.

Only the per-pixel part of the pipeline is modelled (WB -> matrix -> tone -> look LUT -> saturation).
Local operators (DRO, Clarity, sharpening, NR) are not; shoot training pairs with DRO off to keep them out.

  sonysim.py pairs  OUT.npz  A.ARW [B.ARW ...] [--target A.HIF ...]
  sonysim.py fit    MODEL.npz PAIRS.npz [PAIRS2.npz ...] [--cube FL.cube] [--size 33] [--smooth 1] [--neutral W]
  sonysim.py eval   MODEL.npz PAIRS.npz            (dE2000 of the model on pairs it was not fitted on)
  sonysim.py render MODEL.npz IN.(ARW|DNG) OUT.(jpg|tif) [--ev 0] [--half]
  sonysim.py compare MODEL.npz A.ARW OUT.jpg       (side by side: input baseline | camera | model)
"""
import argparse, io, sys
import numpy as np
import rawpy
from PIL import Image
from scipy import ndimage, sparse
from scipy.sparse.linalg import spsolve

# ---------------------------------------------------------------- input space

XYZ_TO_SRGB = np.array([[3.2404542, -1.5371385, -0.4985314],
                        [-0.9692660, 1.8760108, 0.0415560],
                        [0.0556434, -0.2040259, 1.0572252]])
SRGB_TO_XYZ = np.linalg.inv(XYZ_TO_SRGB)
XYZ_TO_REC2020 = np.array([[1.7166512, -0.3556708, -0.2533663],
                           [-0.6666844, 1.6164812, 0.0157685],
                           [0.0176399, -0.0427706, 0.9421031]])

LOG_MIN, LOG_MAX = -14.0, 2.0          # shaper: log2 range of the LUT input (16 stops; 1.0 = raw white)


def cam_to_rec2020(raw):
    """dcraw's normalisation: rows of cam<-sRGB sum to 1, so WB-balanced camera white maps to D65 white."""
    cam_xyz = np.asarray(raw.rgb_xyz_matrix[:3], float)
    cam_rgb = cam_xyz @ SRGB_TO_XYZ
    cam_rgb /= cam_rgb.sum(1, keepdims=True)
    return XYZ_TO_REC2020 @ SRGB_TO_XYZ @ np.linalg.inv(cam_rgb)


def develop(path, half=True, wb=None, ev=0.0):
    """RAW -> float32 HxWx3 scene-linear Rec.2020 (1.0 = sensor white), plus a mask of clipped pixels."""
    with rawpy.imread(path) as raw:
        cam = raw.postprocess(output_color=rawpy.ColorSpace.raw, gamma=(1, 1), no_auto_bright=True,
                              use_camera_wb=False, user_wb=[1, 1, 1, 1], output_bps=16, half_size=half,
                              user_flip=0, highlight_mode=rawpy.HighlightMode.Clip, bright=1.0)
        mul = np.asarray(wb if wb is not None else raw.camera_whitebalance[:3], float)
        mul = mul / mul[1]
        M = cam_to_rec2020(raw)
    cam = cam.astype(np.float32) / 65535.0
    clipped = cam.max(-1) > 0.98
    lin = (cam * mul.astype(np.float32)) @ M.T.astype(np.float32)
    return lin * np.float32(2.0 ** ev), clipped


def shaper(lin):
    return (np.log2(np.maximum(lin, 2.0 ** LOG_MIN)) - LOG_MIN) / (LOG_MAX - LOG_MIN)


# ---------------------------------------------------------------- camera output

def camera_image(arw, target=None):
    """Camera rendering as float sRGB-encoded 0..1: the HEIF/JPEG given, else the ARW's own JpgFromRaw."""
    if target is None:
        with rawpy.imread(arw) as raw:
            th = raw.extract_thumb()
        im = Image.open(io.BytesIO(th.data))
    elif target.lower().endswith(('.hif', '.heic', '.heif')):
        import pillow_heif
        hf = pillow_heif.open_heif(target, convert_hdr_to_8bit=False)
        a = np.asarray(hf[0] if hasattr(hf, '__getitem__') else hf)
        return a.astype(np.float32) / (65535.0 if a.dtype == np.uint16 else 255.0)
    else:
        im = Image.open(target)
    a = np.asarray(im.convert('RGB'))
    return a.astype(np.float32) / 255.0


def luma(img):
    return img @ np.array([0.2126, 0.7152, 0.0722], np.float32)


def box_down(img, f):
    h, w = img.shape[0] // f * f, img.shape[1] // f * f
    img = img[:h, :w]
    return img.reshape(h // f, f, w // f, f, *img.shape[2:]).mean((1, 3))


# ---------------------------------------------------------------- registration

def _tile_shift(a, b):
    """Sub-pixel shift d such that a(x) ~ b(x + d), by phase correlation."""
    win = np.outer(np.hanning(a.shape[0]), np.hanning(a.shape[1]))
    A = np.fft.fft2((a - a.mean()) * win)
    B = np.fft.fft2((b - b.mean()) * win)
    R = A.conj() * B
    r = np.fft.ifft2(R / (np.abs(R) + 1e-9)).real
    iy, ix = np.unravel_index(np.argmax(r), r.shape)
    peak = r[iy, ix]
    def sub(c, m, n):
        return 0.5 * (m - n) / (m - 2 * c + n) if (m - 2 * c + n) != 0 else 0.0
    dy = iy + sub(peak, r[iy - 1, ix], r[(iy + 1) % r.shape[0], ix])
    dx = ix + sub(peak, r[iy, ix - 1], r[iy, (ix + 1) % r.shape[1]])
    dy = dy - r.shape[0] if dy > r.shape[0] / 2 else dy
    dx = dx - r.shape[1] if dx > r.shape[1] / 2 else dx
    return dy, dx, peak


def _model_coords(params, qy, qx, cj, cr, norm):
    s, k1, k2, ty, tx = params
    dy, dx = (qy - cj[0]) / norm, (qx - cj[1]) / norm
    r2 = dy * dy + dx * dx
    f = s * (1 + k1 * r2 + k2 * r2 * r2)
    return cr[0] + norm * f * dy + ty, cr[1] + norm * f * dx + tx


def register(src_lin, cam, tile=96, iters=4, log=print):
    """Find the map JPEG pixel -> src pixel: p = c_src + s*(1 + k1 r^2 + k2 r^4)*(q - c_jpg) + t."""
    g_cam = luma(cam)
    g_src = luma(np.clip(src_lin / max(np.percentile(src_lin, 99), 1e-6), 0, 1)) ** (1 / 2.2)
    H, W = g_cam.shape
    cj = np.array([(H - 1) / 2, (W - 1) / 2])
    cr = np.array([(g_src.shape[0] - 1) / 2, (g_src.shape[1] - 1) / 2])
    norm = np.hypot(*cj)
    params = np.array([g_src.shape[1] / W, 0, 0, 0, 0], float)
    ys = np.arange(tile, H - 2 * tile, tile)
    xs = np.arange(tile, W - 2 * tile, tile)
    for it in range(iters):
        qy, qx = np.meshgrid(np.arange(H, dtype=np.float32), np.arange(W, dtype=np.float32), indexing='ij')
        py, px = _model_coords(params, qy, qx, cj, cr, norm)
        warped = ndimage.map_coordinates(g_src, [py, px], order=1, mode='nearest')
        Q, P = [], []
        for y in ys:
            for x in xs:
                a = g_cam[y:y + tile, x:x + tile]
                b = warped[y:y + tile, x:x + tile]
                if a.std() < 0.02:
                    continue
                dy, dx, pk = _tile_shift(a, b)
                if pk < 0.08 or abs(dy) > tile / 3 or abs(dx) > tile / 3:
                    continue
                # cam(q) matches warped(q + d)  -> src point = model(q + d)
                q = (y + tile / 2 - 0.5, x + tile / 2 - 0.5)
                P.append(_model_coords(params, q[0] + dy, q[1] + dx, cj, cr, norm))
                Q.append(q)
        Q, P = np.array(Q), np.array(P)
        # linear LSQ in (s, s*k1, s*k2, ty, tx)
        dy, dx = (Q[:, 0] - cj[0]) / norm, (Q[:, 1] - cj[1]) / norm
        r2 = dy * dy + dx * dx
        rows = []
        for d, t in ((dy, (1, 0)), (dx, (0, 1))):
            rows.append(np.stack([norm * d, norm * d * r2, norm * d * r2 * r2,
                                  np.full_like(d, t[0]), np.full_like(d, t[1])], 1))
        A = np.concatenate(rows)
        b = np.concatenate([P[:, 0] - cr[0], P[:, 1] - cr[1]])
        keep = np.ones(len(b), bool)
        for _ in range(3):
            sol = np.linalg.lstsq(A[keep], b[keep], rcond=None)[0]
            res = np.abs(A @ sol - b)
            keep = res < max(3 * np.median(res[keep]), 0.5)
        params = np.array([sol[0], sol[1] / sol[0], sol[2] / sol[0], sol[3], sol[4]])
        n = len(Q)
        rms = np.sqrt(np.mean(res[keep] ** 2))
        log(f'  register it{it}: {n} tiles, s={params[0]:.5f} k1={params[1]:+.4f} k2={params[2]:+.4f} '
            f't=({params[3]:+.2f},{params[4]:+.2f}) rms={rms:.2f}px')
    return params, cj, cr, norm


# ---------------------------------------------------------------- pairs

def make_pairs(arw, target=None, down=4, log=print):
    log(f'{arw}')
    lin, clipped = develop(arw, half=True)
    cam = camera_image(arw, target)
    # analysis scale: JPEG / down; develop() is half size (= JPEG/2), so bring it to the same scale
    cam_s = box_down(cam, down)
    lin_s = box_down(lin, down // 2)
    clip_s = box_down(clipped.astype(np.float32), down // 2) > 0
    params, cj, cr, norm = register(lin_s, cam_s, log=log)
    H, W = cam_s.shape[:2]
    qy, qx = np.meshgrid(np.arange(H, dtype=np.float32), np.arange(W, dtype=np.float32), indexing='ij')
    py, px = _model_coords(params, qy, qx, cj, cr, norm)
    src = np.stack([ndimage.map_coordinates(lin_s[..., c], [py, px], order=1, mode='nearest') for c in range(3)], -1)
    clip_w = ndimage.map_coordinates(clip_s.astype(np.float32), [py, px], order=1, mode='nearest') > 0
    # keep flat regions only: robust to residual misregistration, sharpening and chroma subsampling
    sig = 1.5
    src_b = np.stack([ndimage.gaussian_filter(src[..., c], sig) for c in range(3)], -1)
    cam_b = np.stack([ndimage.gaussian_filter(cam_s[..., c], sig) for c in range(3)], -1)
    ls = np.log2(np.maximum(luma(src_b), 2 ** -14))
    grad = np.hypot(*np.gradient(ndimage.gaussian_filter(luma(cam_s), 1.0)))
    gsrc = np.hypot(*np.gradient(ndimage.gaussian_filter(ls, 1.0)))
    flat = (grad < 0.01) & (gsrc < 0.08)
    flat = ndimage.binary_erosion(flat, iterations=2)
    border = np.zeros_like(flat)
    border[8:-8, 8:-8] = True
    ok = flat & border & ~ndimage.binary_dilation(clip_w, iterations=3) & (cam_b.max(-1) < 0.995)
    log(f'  samples: {ok.sum()} flat px of {ok.size}')
    return src_b[ok].astype(np.float32), cam_b[ok].astype(np.float32), params


def cmd_pairs(a):
    X, Y, info = [], [], []
    targets = a.target or [None] * len(a.raws)
    for i, (r, t) in enumerate(zip(a.raws, targets)):
        x, y, p = make_pairs(r, t)
        X.append(x); Y.append(y); info.append(np.full(len(x), i))
    np.savez_compressed(a.out, x=np.concatenate(X), y=np.concatenate(Y), img=np.concatenate(info),
                        names=np.array(a.raws))
    print(f'wrote {a.out}')


# ---------------------------------------------------------------- LUT fit

def _bin(xe, y, nb=64):
    """Average samples into nb^3 cells of the shaped input (keeps the fit size bounded, equalises regions)."""
    idx = np.clip((xe * nb).astype(int), 0, nb - 1)
    key = (idx[:, 0] * nb + idx[:, 1]) * nb + idx[:, 2]
    u, inv, cnt = np.unique(key, return_inverse=True, return_counts=True)
    xs = np.stack([np.bincount(inv, xe[:, c]) for c in range(3)], 1) / cnt[:, None]
    ys = np.stack([np.bincount(inv, y[:, c]) for c in range(3)], 1) / cnt[:, None]
    return xs, ys, cnt


def _trilinear_matrix(xe, n):
    g = np.clip(xe, 0, 1) * (n - 1)
    i0 = np.minimum(g.astype(int), n - 2)
    f = g - i0
    rows, cols, vals = [], [], []
    m = len(xe)
    for dr in (0, 1):
        for dg in (0, 1):
            for db in (0, 1):
                w = ((f[:, 0] if dr else 1 - f[:, 0]) * (f[:, 1] if dg else 1 - f[:, 1]) *
                     (f[:, 2] if db else 1 - f[:, 2]))
                col = ((i0[:, 0] + dr) * n + i0[:, 1] + dg) * n + i0[:, 2] + db
                rows.append(np.arange(m)); cols.append(col); vals.append(w)
    return sparse.csr_matrix((np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))), shape=(m, n ** 3))


def _laplacian(n):
    """Second differences along r, g, b: smoothness prior; its null space is affine, so empty regions extrapolate."""
    I = sparse.identity(n, format='csr')
    D = sparse.diags([np.ones(n - 2), -2 * np.ones(n - 2), np.ones(n - 2)], [0, 1, 2], shape=(n - 2, n))
    ops = [sparse.kron(sparse.kron(D, I), I), sparse.kron(sparse.kron(I, D), I), sparse.kron(sparse.kron(I, I), D)]
    return sparse.vstack(ops).tocsr()


def _solve(xs, ys, w, n, smooth):
    A = _trilinear_matrix(xs, n)
    Wd = sparse.diags(w)
    L = _laplacian(n)
    lam = smooth * len(xs) / L.shape[0]
    lhs = (A.T @ Wd @ Wd @ A + lam * (L.T @ L) + 1e-6 * sparse.identity(n ** 3)).tocsc()
    rhs = A.T @ (Wd @ Wd @ ys)
    V = np.stack([spsolve(lhs, rhs[:, c]) for c in range(3)], 1)
    return np.clip(V, 0, 1).reshape(n, n, n, 3).astype(np.float32)


def fit_lut(x_lin, y, n=33, smooth=1.0, neutral=0.0):
    """neutral > 0: also ask that equal-RGB input gives grey output (lightness taken from a first fit), with that
    weight per point. Chart shots under a non-matching WB never sample the true neutral axis, so without this the
    grey balance there is extrapolated."""
    xe = shaper(x_lin)
    xs, ys, cnt = _bin(xe, y)
    w = np.sqrt(cnt)                    # many pixels in one cell count more, but sub-linearly
    w = w / w.mean()
    V = _solve(xs, ys, w, n, smooth)
    if neutral > 0:
        t = np.linspace(0, 1, 4 * n)
        xn = np.repeat(t[:, None], 3, 1)
        yl = luma(apply_lut(V, 2.0 ** (LOG_MIN + t[:, None] * (LOG_MAX - LOG_MIN)) * np.ones((1, 3))).astype(np.float32))
        yn = np.repeat(yl[:, None], 3, 1)        # grey with the first fit's (encoded) luma
        V = _solve(np.concatenate([xs, xn]), np.concatenate([ys, yn]),
                   np.concatenate([w, np.full(len(t), neutral)]), n, smooth)
    return V, len(xs)


def apply_lut(lut, lin):
    n = lut.shape[0]
    shp = lin.shape
    xe = shaper(lin.reshape(-1, 3)).astype(np.float32)
    g = np.clip(xe, 0, 1) * (n - 1)
    i0 = np.minimum(g.astype(np.int32), n - 2)
    f = g - i0
    out = np.zeros((len(xe), 3), np.float32)
    for dr in (0, 1):
        for dg in (0, 1):
            for db in (0, 1):
                w = ((f[:, 0] if dr else 1 - f[:, 0]) * (f[:, 1] if dg else 1 - f[:, 1]) *
                     (f[:, 2] if db else 1 - f[:, 2]))
                out += w[:, None] * lut[i0[:, 0] + dr, i0[:, 1] + dg, i0[:, 2] + db]
    return out.reshape(shp)


def write_cube(path, lut, title):
    n = lut.shape[0]
    with open(path, 'w') as f:
        f.write(f'TITLE "{title}"\n')
        f.write(f'# input: per-channel (log2(linear Rec.2020, D65, WB applied, 1.0 = raw white) - ({LOG_MIN:g})) / {LOG_MAX - LOG_MIN:g}\n')
        f.write('# output: sRGB-encoded display RGB\n')
        f.write(f'LUT_3D_SIZE {n}\n')
        for b in range(n):              # .cube order: red fastest
            for g in range(n):
                for r in range(n):
                    f.write('%.6f %.6f %.6f\n' % tuple(lut[r, g, b]))


def cmd_fit(a):
    X, Y = [], []
    for p in a.pairs:
        d = np.load(p)
        X.append(d['x']); Y.append(d['y'])
    lut, cells = fit_lut(np.concatenate(X), np.concatenate(Y), a.size, a.smooth, a.neutral)
    np.savez_compressed(a.model, lut=lut, log_min=LOG_MIN, log_max=LOG_MAX)
    print(f'fitted {a.size}^3 LUT on {cells} occupied input cells -> {a.model}')
    if a.cube:
        write_cube(a.cube, lut, a.title)
        print(f'wrote {a.cube}')


# ---------------------------------------------------------------- eval / render

def de2000(y_pred, y_true):
    import warnings
    warnings.filterwarnings('ignore')
    import colour
    lab = lambda s: colour.XYZ_to_Lab(colour.sRGB_to_XYZ(np.clip(s, 0, 1)))
    return colour.delta_E(lab(y_pred), lab(y_true), method='CIE 2000')


def cmd_eval(a):
    lut = np.load(a.model)['lut']
    d = np.load(a.pairs)
    for i, name in enumerate(d['names']):
        m = d['img'] == i
        x, y = d['x'][m], d['y'][m]
        e = de2000(apply_lut(lut, x), y)
        # neutral reference: plain sRGB of the input (what "no look" would give), exposure-matched on median luma
        base = np.clip(x @ np.linalg.inv(XYZ_TO_REC2020 @ SRGB_TO_XYZ).T.astype(np.float32), 0, None)
        base *= np.median(luma(y) ** 2.2) / max(np.median(luma(base)), 1e-6)
        e0 = de2000(np.where(base <= 0.0031308, 12.92 * base, 1.055 * np.maximum(base, 0) ** (1 / 2.4) - 0.055), y)
        print(f'{name}: {m.sum()} px  dE2000 mean {e.mean():.2f}  p50 {np.median(e):.2f}  p95 {np.percentile(e, 95):.2f}'
              f'   (plain sRGB baseline mean {e0.mean():.2f})')


def to_srgb_baseline(lin):
    s = np.clip(lin @ np.linalg.inv(XYZ_TO_REC2020 @ SRGB_TO_XYZ).T.astype(np.float32), 0, 1)
    return np.where(s <= 0.0031308, 12.92 * s, 1.055 * s ** (1 / 2.4) - 0.055)


def save(img, path):
    if path.lower().endswith(('.tif', '.tiff')):
        import tifffile
        tifffile.imwrite(path, (np.clip(img, 0, 1) * 65535 + 0.5).astype(np.uint16))
    else:
        Image.fromarray((np.clip(img, 0, 1) * 255 + 0.5).astype(np.uint8)).save(path, quality=95)


def cmd_render(a):
    lut = np.load(a.model)['lut']
    lin, _ = develop(a.raw, half=a.half, ev=a.ev)
    save(apply_lut(lut, lin), a.out)
    print(f'wrote {a.out}')


def cmd_compare(a):
    lut = np.load(a.model)['lut']
    lin, _ = develop(a.raw, half=True)
    cam = camera_image(a.raw, a.target)
    h = 600
    def fit(img):
        im = Image.fromarray((np.clip(img, 0, 1) * 255 + 0.5).astype(np.uint8))
        return np.asarray(im.resize((round(im.width * h / im.height), h), Image.LANCZOS))
    base = to_srgb_baseline(lin)
    base = np.clip(base * (np.median(luma(cam)) / max(np.median(luma(base)), 1e-6)), 0, 1)
    panels = [fit(base), fit(cam), fit(apply_lut(lut, lin))]
    Image.fromarray(np.concatenate(panels, 1)).save(a.out, quality=92)
    print(f'wrote {a.out}  (plain sRGB | camera | model)')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest='cmd', required=True)
    p = sp.add_parser('pairs'); p.add_argument('out'); p.add_argument('raws', nargs='+')
    p.add_argument('--target', nargs='+', help='camera JPEG/HEIF per RAW (default: the ARW embedded JpgFromRaw)')
    p.set_defaults(fn=cmd_pairs)
    p = sp.add_parser('fit'); p.add_argument('model'); p.add_argument('pairs', nargs='+')
    p.add_argument('--size', type=int, default=33); p.add_argument('--smooth', type=float, default=1.0)
    p.add_argument('--neutral', type=float, default=0.0, help='weight of the grey-axis prior (0 = off)')
    p.add_argument('--cube'); p.add_argument('--title', default='a7C II look (black-box fit)')
    p.set_defaults(fn=cmd_fit)
    p = sp.add_parser('eval'); p.add_argument('model'); p.add_argument('pairs'); p.set_defaults(fn=cmd_eval)
    p = sp.add_parser('render'); p.add_argument('model'); p.add_argument('raw'); p.add_argument('out')
    p.add_argument('--ev', type=float, default=0.0); p.add_argument('--half', action='store_true')
    p.set_defaults(fn=cmd_render)
    p = sp.add_parser('compare'); p.add_argument('model'); p.add_argument('raw'); p.add_argument('out')
    p.add_argument('--target'); p.set_defaults(fn=cmd_compare)
    a = ap.parse_args()
    a.fn(a)


if __name__ == '__main__':
    main()

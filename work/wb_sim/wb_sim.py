"""White balance through the film looks: how far does each look's render move when the scene is lit by something other
than daylight, or when AWB misses? Spectral simulation, no camera data for the GR III itself.

Scene: ColorChecker 24 (Ohta spectra) at 3 exposures (-1, 0, +1 EV). Camera: measured spectral sensitivities from the
RIT camspec database (work/sensor_diff/camspec_database.txt): Pentax K-5 (Ricoh/Pentax, Sony APS-C: closest GR III
proxy) and Sony NEX-5N. Pipeline: raw = (reflectance x illuminant) . sensitivities -> white balance gains (ideal AWB =
perfect white; or deliberately wrong) -> camera matrix to linear sRGB (fitted at D65, white-preserving, dE2000)
-> look (Standard or a v15 film: look matrix -> base gamma -> curves -> post matrix).
Reference: the same look applied to the true scene colours adapted to D65 (CAT02), i.e. what a perfect
camera + perfect white balance would hand the look. Reported: mean / max dE2000 between render and reference.
Usage (from re-tools): work/wb_sim/wb_sim.py"""
import sys, json, warnings; sys.path.insert(0, '.'); warnings.filterwarnings('ignore')
import numpy as np, colour
from scipy.optimize import least_squares
from cube_fit import BASE, K, STD_LOOK, de2000
from film_cave import knots_of, expand

SH = colour.SpectralShape(400, 720, 10)
cmf = colour.MSDS_CMFS['CIE 1931 2 Degree Standard Observer'].copy().align(SH).values
R = np.array([sd.copy().align(SH).values for sd in colour.SDS_COLOURCHECKERS['ColorChecker N Ohta'].values()])
ILL = {k: colour.SDS_ILLUMINANTS[k].copy().align(SH).values for k in
       ('D65', 'D50', 'D75', 'A', 'FL2', 'FL11', 'LED-B3', 'LED-B5')}
LABEL = {'D65': 'daylight 6500K', 'D50': 'sun 5000K', 'D75': 'shade 7500K', 'A': 'tungsten 2856K',
         'FL2': 'cool-white fluorescent', 'FL11': 'tri-band fluorescent', 'LED-B3': 'white LED 4100K', 'LED-B5': 'white LED 3000K'}


def cams(path='work/sensor_diff/camspec_database.txt'):
    L = open(path).read().split('\n'); out = {}; i = 0
    while i < len(L):
        if L[i].strip() and len(L[i].split()) < 5:
            out[L[i].strip()] = np.stack([np.array(L[i + k].split(), float) for k in (1, 2, 3)], 1); i += 4
        else:
            i += 1
    return out


SRGB = colour.RGB_COLOURSPACES['sRGB']
wD65 = ILL['D65'] @ cmf; wD65 = wD65 / wD65[1]


def truth(I):
    """Scene under I, adapted to D65 (CAT02), linear sRGB with the perfect white = 1."""
    X = (R * I) @ cmf; w = I @ cmf
    X, w = X / w[1], w / w[1]
    Xa = colour.adaptation.chromatic_adaptation_VonKries(X, w, wD65, transform='CAT02')
    return colour.XYZ_to_RGB(Xa, SRGB, apply_cctf_encoding=False)


def lab_lin(L):
    return colour.XYZ_to_Lab(colour.RGB_to_XYZ(np.clip(L, 1e-6, None), SRGB, apply_cctf_decoding=False))


def cam_matrix(S, I=None):
    """Camera matrix (default at D65): white-balanced raw -> linear sRGB, white-preserving, fitted on dE2000."""
    I = ILL['D65'] if I is None else I
    c = (R * I) @ S; c = c / (I @ S)
    t = truth(I)
    M0 = np.linalg.lstsq(c, t, rcond=None)[0].T
    def Mof(p):
        M = p.reshape(3, 3); return M / M.sum(1, keepdims=True)
    f = lambda p: colour.delta_E(lab_lin(c @ Mof(p).T), lab_lin(t), method='CIE 2000')
    return Mof(least_squares(f, M0.ravel()).x)


def camera(S, I, Mcam, wb_from=None, g_shift=1.0):
    c = (R * I) @ S
    w = (wb_from if wb_from is not None else I) @ S                  # AWB = gains from this light's white
    g = w / w[1]                                                     # gains normalised to green = 1
    c = c / g / (I @ S)[1] * np.array([1, g_shift, 1])               # exposure: the scene's white green = 1
    return c @ Mcam.T


F12, F11, F14 = 'work/films_v12/fits/', 'work/films_v11/fits/', 'work/films_v14/fits/'
FILMS = [('Portra 400', F12 + 'portra_b4n3_lab.json'), ('Ektar 100', F12 + 'ektar_b1n3_lab.json'),
         ('Gold 200', F12 + 'gold_b4n3_lab.json'), ('Pro 400H', F12 + 'pro400h_own_b4n3_lab.json'),
         ('Vision3 250D', F11 + 'vision3250d_2383_b4n3_lab.json'), ('Classic Neg', F12 + 'classicneg_b4n3_lab.json'),
         ('Cinema Y', F14 + 'cinema_yellow.json'), ('Cinema G', F14 + 'cinema_green.json'),
         ('Vision3 500T', F14 + 'vision3500t_2383_b4n3_lab.json')]


def look(M, cv, P):
    def r(L):
        z = (K * L) @ M.T
        b = np.interp(np.clip(z, 0, 255), np.arange(256), BASE)
        return np.clip(np.stack([np.interp(b[:, c] / 64, np.arange(256), cv[c]) for c in range(3)], 1) / 16384 @ P.T, 0, 1)
    return r


LOOKS = {'Standard': look(STD_LOOK, [np.minimum(np.arange(256) * 64.0, 16383)] * 3, np.eye(3))}
for name, fp in FILMS:
    f = json.load(open(fp)); cv = f['presets'][0]['curves']
    cv = [np.array(c, float) for c in cv] if 'cinema' in fp else [expand(knots_of(c)) for c in cv]
    LOOKS[name] = look(np.array(f['matrix']), cv, np.array(f['post_q512']) / 512)

EV = (0.5, 1.0, 2.0)
stack = lambda a: np.concatenate([a * e for e in EV])


def table(title, cases, S, Mcam):
    print(f'\n{title}\n{"case":34s} ' + ' '.join(f'{k[:10]:>10s}' for k in LOOKS))
    for label, I, kw in cases:
        M = cam_matrix(S, I) if kw.pop('own_matrix', False) else Mcam
        Lc, Lt = stack(camera(S, I, M, **kw)), stack(truth(I))
        row = []
        for k, f in LOOKS.items():
            e = de2000(f(Lc), f(Lt)); row.append(f'{e.mean():4.2f}/{e.max():4.1f}')
        print(f'{label:34s} ' + ' '.join(f'{x:>10s}' for x in row))


C = cams()
for cam in ('Pentax K-5', 'SONY NEX-5N'):
    S = C[cam]; Mcam = cam_matrix(S)
    print(f'\n===== {cam} (camera matrix fitted at D65) =====  dE2000 mean/max vs perfect camera + perfect WB')
    table('A) ideal AWB, one fixed (D65) camera matrix, light varies',
          [(LABEL[k], ILL[k], {}) for k in ILL], S, Mcam)
    cct = lambda T: colour.sd_CIE_illuminant_D_series(colour.temperature.CCT_to_xy_CIE_D(T * 1.4388 / 1.4380)).copy().align(SH).values
    bb = lambda T: colour.sd_blackbody(T, SH).values
    table('A2) as A, but a camera matrix made for each light (what a CCT-interpolated matrix could reach)',
          [(LABEL[k], ILL[k], dict(own_matrix=True)) for k in ('A', 'FL2', 'FL11', 'LED-B3')], S, Mcam)
    table('B) daylight 6500K scene, AWB misses',
          [('AWB thinks 5500K (too warm comp.)', ILL['D65'], dict(wb_from=cct(5500))),
           ('AWB thinks 7500K', ILL['D65'], dict(wb_from=cct(7500))),
           ('green -3% (magenta cast)', ILL['D65'], dict(g_shift=0.97)),
           ('green +3% (green cast)', ILL['D65'], dict(g_shift=1.03))], S, Mcam)
    table('C) tungsten 2856K scene, AWB misses (typical: leaves it warm)',
          [('AWB perfect', ILL['A'], {}),
           ('AWB thinks 3200K (slightly warm)', ILL['A'], dict(wb_from=bb(3200))),
           ('AWB thinks 3500K (warm, "atmosphere")', ILL['A'], dict(wb_from=bb(3500)))], S, Mcam)

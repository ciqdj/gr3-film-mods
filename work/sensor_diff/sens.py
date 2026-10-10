import sys, warnings, numpy as np, itertools; warnings.filterwarnings('ignore')
import colour
from scipy.optimize import least_squares
L = open(sys.argv[1]).read().split('\n'); cams = {}
i = 0
while i < len(L):
    if L[i].strip() and len(L[i].split()) < 5:
        n = L[i].strip(); r = [np.array(L[i+k].split(), float) for k in (1, 2, 3)]; cams[n] = np.stack(r, 1); i += 4
    else: i += 1
wl = np.arange(400, 721, 10)
cmf = colour.MSDS_CMFS['CIE 1931 2 Degree Standard Observer'].copy().align(colour.SpectralShape(400, 720, 10)).values
def refl(name):
    return np.array([sd.copy().align(colour.SpectralShape(400, 720, 10)).values for sd in colour.SDS_COLOURCHECKERS[name].values()])
R = refl('ColorChecker N Ohta')
ill = {k: colour.SDS_ILLUMINANTS[k].copy().align(colour.SpectralShape(400, 720, 10)).values for k in ('D65', 'A')}
def resp(S, I): return (R * I) @ S
def lab(XYZ, wp): return colour.XYZ_to_Lab(XYZ / 100, colour.XYZ_to_xy(wp))
def de(a, b, wp): return colour.delta_E(lab(a, wp), lab(b, wp), method='CIE 2000')
def fit(src, dst, wsrc, wdst):
    # white-preserving 3x3: M wsrc = wdst; minimise dE in dst-as-XYZ (caller passes XYZ dst)
    def M_of(p):
        M = p.reshape(3, 3); s = wdst / (M @ wsrc); return M * s[:, None]
    M0 = np.linalg.lstsq(src, dst, rcond=None)[0].T
    f = lambda p: de(src @ M_of(p).T, dst, wdst)
    return M_of(least_squares(f, M0.ravel()).x)
out = {}
for I in ('D65', 'A'):
    X = resp(cmf, ill[I]); wX = ill[I] @ cmf; nX = 100 / wX[1]; X, wX = X * nX, wX * nX
    for n, S in cams.items():
        C = resp(S, ill[I]); wC = ill[I] @ S
        M = fit(C, X, wC, wX); out[(n, I)] = M
        e = de(C @ M.T, X, wX); cams_err = out.setdefault(('err', I), {}); cams_err[n] = (e.mean(), e.max())
print('1) camera -> human (XYZ), best white-preserving 3x3 on ColorChecker, dE2000 mean / max')
print(f'{"camera":28s} {"D65":>12s} {"A":>12s}')
for n in cams: print(f'{n:28s} ' + ' '.join(f'{out[("err",I)][n][0]:5.2f}/{out[("err",I)][n][1]:5.2f}' for I in ('D65', 'A')))
# 2) port a look from camera B to camera A: A raw -> best 3x3 -> B raw; error in B's colour (B raw via B's D65 matrix to XYZ)
I = 'D65'; X = resp(cmf, ill[I]); wX = ill[I] @ cmf; nX = 100 / wX[1]; wX = wX * nX
def port(a, b):
    Ca, Cb = resp(cams[a], ill[I]), resp(cams[b], ill[I]); Mb = out[(b, I)]
    Xb = Cb @ Mb.T                                      # what B "sees" (its own XYZ estimate)
    M = fit(Ca, Xb, ill[I] @ cams[a], wX)               # best A->B (in XYZ terms)
    return de(Ca @ M.T, Xb, wX)
names = list(cams); P = {}
for a, b in itertools.permutations(names, 2): P[a, b] = port(a, b)
m = np.array([v.mean() for v in P.values()]); mx = np.array([v.max() for v in P.values()])
print(f'\n2) cross-camera port (A raw -> best 3x3 -> B), all {len(P)} pairs, D65: mean dE2000 median {np.median(m):.2f}, '
      f'90th pct {np.percentile(m,90):.2f}, worst {m.max():.2f}; worst patch median {np.median(mx):.2f}, worst {mx.max():.2f}')
for a, b in [('Pentax K-5', 'Hasselblad H2'), ('Pentax K-5', 'SONY NEX-5N'), ('Pentax K-5', 'Phase One'), ('Pentax K-5', 'Canon 5DMarkII'),
             ('Pentax K-5', 'Nikon D3X'), ('SONY NEX-5N', 'Nikon D5100'), ('Pentax K-5', 'Nokia N900')]:
    e = P[a, b]; w = np.argsort(e)[-3:][::-1]; nm = list(colour.SDS_COLOURCHECKERS['ColorChecker N Ohta'])
    print(f'  {a:12s} -> {b:15s} mean {e.mean():4.2f} max {e.max():4.2f}  worst: ' + ', '.join(f'{nm[k]} {e[k]:.1f}' for k in w))
# 3) illuminant dependence: matrix fitted at D65 used under A (after WB), vs matrix fitted at A
print('\n3) same camera, D65 matrix reused under tungsten (A) after white balance, dE2000 mean/max  vs own A matrix')
XA = resp(cmf, ill['A']); wA = ill['A'] @ cmf; nA = 100 / wA[1]; XA, wA = XA * nA, wA * nA
for n in ('Pentax K-5', 'SONY NEX-5N', 'Hasselblad H2', 'Canon 5DMarkII'):
    C = resp(cams[n], ill['A']); wC = ill['A'] @ cams[n]
    Md = out[(n, 'D65')]; wD = ill['D65'] @ cams[n]
    Cw = C * (wD / wC)                                       # von Kries WB in camera space
    Y = Cw @ Md.T; Y = colour.chromatic_adaptation(Y, colour.XYZ_to_xy(ill['D65'] @ cmf) * 0 + (ill['D65'] @ cmf) / (ill['D65'] @ cmf)[1] * 100, wA, method='Von Kries', transform='CAT02') if False else Y
    # compare in a D65-adapted frame: adapt true XYZ under A to D65 with CAT02
    wD65 = ill['D65'] @ cmf; wD65 = wD65 / wD65[1] * 100
    Xt = colour.adaptation.chromatic_adaptation_VonKries(XA, wA, wD65, transform='CAT02')
    Y = Y / (wD @ Md.T)[1] * 100
    e = de(Y, Xt, wD65)
    print(f'  {n:15s} {e.mean():4.2f}/{e.max():4.2f}   own-A fit {out[("err","A")][n][0]:4.2f}/{out[("err","A")][n][1]:4.2f}')

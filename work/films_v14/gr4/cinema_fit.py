"""Extract GR IV Cinema (Yellow)/(Green) as GR III film fits: matrix = (L4cin L4std^-1) STD_LOOK, curves = GR IV mixed
R/G/B curves at the default Color Tone (1), post = identity. Writes re-tools/work/films_v14/fits/cinema_{yellow,green}.json"""
import sys, os, json, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from g4curves import curves, g
BASE = np.load("work/base_gamma_std.npy").astype(float)
STD_LOOK = np.array([8116, 743, -667, 15, 8598, -421, -244, 542, 7894]).reshape(3, 3) / 8192
L4 = lambda rec: np.array(g.h(g.w(rec + 4), 9), float).reshape(3, 3) / 8192
std_rec = g.w(0x55053780 + 4 * 11)
L4std = L4(std_rec)
print('GR4 std look', (L4std * 8192).round().astype(int).tolist(), 'GR3 std', (STD_LOOK * 8192).round().astype(int).tolist())
c11 = curves(11, 1)
print('base GR4 vs GR3 max diff', np.abs(c11['base'] - BASE).max())
o11 = None
out = {}
for key, tone in (('cinema_yellow', 18), ('cinema_green', 19)):
    rec = g.w(0x55053780 + 4 * tone)
    S = L4(rec) @ np.linalg.inv(L4std)
    M = S @ STD_LOOK
    c = curves(tone, 1)
    assert c['mix'] == (1, 2), c['mix']
    cv = [x.tolist() for x in c['curves']]
    # composite check: comp == curve(base)
    for k in range(3):
        idx = np.clip(c['base'], 0, 16383) / 64
        pred = np.interp(np.minimum(idx, 255), np.arange(256), c['curves'][k])
        print(key, 'ch', k, 'comp-vs-curve(base) max', np.abs(pred - c['comp'][k]).max())
    print(key, 'S', S.round(4).tolist(), 'rowsum M', M.sum(1).round(4))
    fit = dict(matrix=M.tolist(), post_q512=[[512, 0, 0], [0, 512, 0], [0, 0, 512]], mid_index=7.8,
               source=f'GR IV fwdc248b tone {tone}, Color Tone 1 (default), MultiAxial not ported',
               presets=[dict(spec=f'gr4:{tone}', curves=cv)])
    json.dump(fit, open(f'work/films_v14/fits/{key}.json', 'w'))

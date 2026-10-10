"""Score of each LUTSmith-method look with its exact 256-entry curves vs the 33-knot curves the firmware stores."""
import sys, json; sys.path.insert(0, '.')
import numpy as np
from cube_fit import samples, warm_samples, target_of, model, de2000
from film_cave import knots_of, expand
chart = np.load('work/films_v10/camera_chart_L.npy'); warm = warm_samples(n=1200, seed=11); Lg, _, cc = samples(seed=7)
SETS = [('general', Lg[600:]), ('warm', warm), ('ColorChecker', cc), ('camera chart', chart)]
for p in sys.argv[1:]:
    f = json.load(open(p)); T = target_of(f['presets'][0]); M = np.array(f['matrix']); P = np.array(f['post_q512']) / 512
    for nm, cv in (('exact', [np.array(c) for c in f['presets'][0]['curves']]), ('knots', [expand(knots_of(c)) for c in f['presets'][0]['curves']])):
        s = []
        for n, X in SETS:
            t = T(X); u = t.min(1) > 0.02 if n == 'camera chart' else np.ones(len(X), bool)
            s.append(de2000(np.clip(model(M, cv, X) @ P.T, 0, 1)[u], t[u]).mean())
        print(p.split('/')[-1], nm, ' / '.join(f'{x:.2f}' for x in s))

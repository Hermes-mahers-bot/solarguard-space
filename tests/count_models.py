"""Count what we trained, correctly: per bundle -> trees, MLP shape, blend."""
import json
import os
import sys

import numpy as np

sys.path.insert(0, "ml")
import ai_features as F

tot_trees = tot_w = 0
rows = []
for name in sorted(f for f in os.listdir("models/ai") if f.endswith(".npz")):
    z = np.load(f"models/ai/{name}", allow_pickle=False)
    meta = json.loads(str(np.asarray(z["meta_json"]).ravel()[0]))
    # the classifiers store their tree model under a clf_ prefix, the regressors
    # under gbrt_ — same implementation, different key name
    pre = "clf" if "clf_n_trees" in z.files else "gbrt"
    ntrees = int(np.asarray(z[f"{pre}_n_trees"]).ravel()[0]) if f"{pre}_n_trees" in z.files else 0
    depth = int(np.asarray(z[f"{pre}_max_depth"]).ravel()[0]) if f"{pre}_max_depth" in z.files else 0
    lr = float(np.asarray(z[f"{pre}_learning_rate"]).ravel()[0]) if f"{pre}_learning_rate" in z.files else 0
    layers = [z[k].shape for k in ("mlp_W0", "mlp_W1", "mlp_W2") if k in z.files]
    w = np.asarray(z["w"]).ravel() if "w" in z.files else None
    nw = sum(int(np.prod(s)) for s in layers) + sum(int(z[k].size) for k in ("mlp_b0", "mlp_b1", "mlp_b2") if k in z.files)
    tot_trees += ntrees
    tot_w += nw
    arch = " -> ".join(str(s[0]) for s in layers) + " -> " + str(layers[-1][1]) if layers else "?"
    rows.append((name, ntrees, depth, lr, arch, nw,
                 f"{w[0]:.2f} trees / {w[1]:.2f} net" if w is not None else "n/a"))

print(f"{'bundle':14} {'trees':>6} {'depth':>5} {'lr':>6}  {'neural net':26} {'weights':>8}  blend")
print("-" * 92)
for r in rows:
    print(f"{r[0]:14} {r[1]:>6} {r[2]:>5} {r[3]:>6}  {r[4]:26} {r[5]:>8,}  {r[6]}")
print("-" * 92)
print(f"{'TOTAL':14} {tot_trees:>6}          {'':26} {tot_w:>8,}")
print(f"\nshipped bundles      : {len(rows)}")
print(f"trained models total : {len(rows) * 2}  (each bundle blends one tree model and one neural net)")
print(f"features per model   : {len(F.FEATURES)}")
print(f"training data        : 17,772 samples from 18,348 harvested site-days, 12 sites")
print(f"trained in           : one run of ml/ai_train.py, 966 seconds, CPU only")

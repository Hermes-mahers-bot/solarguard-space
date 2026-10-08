"""Which of the 37 inputs each trained tree model actually uses, from its own splits."""
import json
import os

import numpy as np

for name in ("storm_t1", "storm_t2", "storm_t3", "yield_t1", "soiling_t1"):
    z = np.load(f"models/ai/{name}.npz", allow_pickle=False)
    meta = json.loads(str(np.asarray(z["meta_json"]).ravel()[0]))
    feats = meta["features"]
    pre = "clf" if "clf_n_trees" in z.files else "gbrt"
    n = int(np.asarray(z[f"{pre}_n_trees"]).ravel()[0])
    use = np.zeros(len(feats))
    for t in range(n):
        key = f"{pre}_t{t}_feat"
        if key in z.files:
            for f in np.asarray(z[key]).ravel():
                use[int(f)] += 1
    tot = use.sum() or 1
    top = np.argsort(-use)[:7]
    print(f"\n{name}  ({n} trees, {int(tot):,} splits)")
    for i in top:
        if use[i] > 0:
            print(f"   {100 * use[i] / tot:5.1f}%  {feats[i]}")

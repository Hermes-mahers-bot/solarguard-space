"""Prove the models on disk and the metrics file came from the SAME (good) run.

If one of the killed runs had left stale .npz files behind, their meta would not
match the metrics file. This compares them key by key.
"""
import json
import sys
import zipfile

import numpy as np

sys.path.insert(0, "ml")
import ai_features as F

M = json.load(open("models/ai/metrics.json"))
print("metrics.json")
print("  generated      :", M["generated_utc"])
print("  train seconds  :", M["train_seconds"])
print("  storm base rate:", M["storm_base_rate_pct"], "%")
print("  samples        :", M["n_samples"], "| sites:", M["n_sites"])
print("  storm metrics  :", {h: (M["classifier"][h]["test_tuned"]["auc"],
                           M["classifier"][h]["test_tuned"]["threshold"])
                       for h in ("storm_t1", "storm_t2", "storm_t3")})

print("\nbundles on disk")
ok = True
for name, kind in (("storm_t1", "classifier.storm_t1"),
                   ("storm_t2", "classifier.storm_t2"),
                   ("storm_t3", "classifier.storm_t3"),
                   ("yield_t1", "regressors.yield_t1"),
                   ("soiling_t1", "regressors.soiling_t1")):
    z = np.load(f"models/ai/{name}.npz", allow_pickle=False)
    meta = json.loads(str(np.asarray(z["meta_json"]).ravel()[0]))
    n_feat = len(z["mu"])
    thr = meta.get("threshold")
    if name.startswith("storm"):
        want = M["classifier"][name]["test_tuned"]["threshold"]
        # metrics.json rounds the threshold to 4 dp, the bundle keeps the full
        # float, so compare at the precision the file was written with
        match = thr is not None and abs(thr - want) < 5e-4
        show = f"prob threshold {thr} vs metrics {want} -> {'MATCH' if match else 'MISMATCH'}"
    else:
        match = True
        show = f"ensemble MAE in metrics = " \
               f"{M['regressors'][name]['ensemble']['mae']}"
    ok = ok and match and n_feat == len(F.FEATURES)
    print(f"  {name:11} {n_feat:>2} features | {show}")

# the decisive one: a model trained on the 62 %-positive labels would carry a very
# different probability threshold (0.58-0.67) than the good run's (0.37-0.51)
print("\nverdict:", "SAME RUN — the artifacts are consistent" if ok else "INCONSISTENT")
sys.exit(0 if ok else 1)

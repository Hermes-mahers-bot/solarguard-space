"""Train the SolarGuard AI: sandstorm classifier + output and soiling regressors.

    python3 ml/ai_train.py            # full run (time split + leave-one-site-out)
    python3 ml/ai_train.py --quick    # time split only, for iteration

Everything is hand-rolled numpy (no sklearn / xgboost / torch available on this
box, and no GPU). The tree machinery is reused from ml/train.py; this file adds a
logistic-loss gradient-boosting classifier and the evaluation protocol.

WHAT THIS PREDICTS (the honest framing, and the reason it works this time)
  storm_t1/t2/t3   P(sandstorm on day t+1, t+2, t+3)  <- a real, measured label:
                   CAMS PM10 daily max >= 200 ug/m3 over that site, 2022-08+
  yield_t1         kWh per kWp for day t+1            <- documented PV model on
                   measured irradiation and air temperature
  soiling_t1       optical loss % on day t+1          <- documented deposition
                   model on measured PM10/dust/gust/rain

No future information enters the features: a row dated t sees rows[0..t] only, so
t+1..t+3 are genuinely unseen at prediction time. Every feature can be rebuilt at
inference from the live forecast window (92 days of past + N days ahead), which is
checked by tests/test_ai.py.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)

import train as T                                   # noqa: E402  (GBRT, MLP)
import ai_features as F                             # noqa: E402

CSV_PATH = os.path.join(ROOT, "data", "ai", "daily.csv")
OUT_DIR = os.path.join(ROOT, "models", "ai")
METRICS_PATH = os.path.join(OUT_DIR, "metrics.json")

VAL_START = "2025-10-01"      # validation block (threshold tuning)
TEST_START = "2026-04-01"     # untouched test block


# ═════════════════════════════════════════════════════════ logistic GBRT
class GBRTClassifier(T.GBRT):
    """Gradient-boosted trees with logistic loss (binary), numpy only.

    The parent class does squared-error boosting, which is wrong for a rare-event
    probability: it optimises the residual, not the log-loss, and its leaves are
    means rather than Newton steps. This subclass keeps the parent's binning and
    prediction machinery and swaps in gradient/hessian splitting.
    """

    def __init__(self, n_trees=300, max_depth=3, learning_rate=0.08,
                 min_samples_leaf=30, max_bins=32, subsample=0.85, colsample=0.75,
                 l2=1.0, seed=0):
        super().__init__(n_trees=n_trees, max_depth=max_depth,
                         learning_rate=learning_rate, min_samples_leaf=min_samples_leaf,
                         max_bins=max_bins, subsample=subsample, colsample=colsample,
                         l2=l2, seed=seed)

    @staticmethod
    def _sigmoid(z):
        return 0.5 * (1.0 + np.tanh(0.5 * z))

    def _grow_lr(self, B, g, h, idx, depth, n_feat_try):
        n = len(idx)
        G = float(np.sum(g[idx]))
        H = float(np.sum(h[idx]))
        leaf = -G / (H + self.l2)
        if depth >= self.max_depth or n < 2 * self.min_samples_leaf:
            return {"feat": -1, "thr": -1, "left": -1, "right": -1, "value": leaf}
        parent_gain = G * G / (H + self.l2)
        best_gain, best_j, best_k = 1e-9, -1, -1
        feats = self.rng.choice(B.shape[1], size=min(n_feat_try, B.shape[1]), replace=False)
        for j in feats:
            b = B[idx, j]
            cg = np.bincount(b, weights=g[idx], minlength=self.max_bins)
            ch = np.bincount(b, weights=h[idx], minlength=self.max_bins)
            cnt = np.bincount(b, minlength=self.max_bins)
            GL = np.cumsum(cg)[:-1]
            HL = np.cumsum(ch)[:-1]
            CL = np.cumsum(cnt)[:-1].astype(float)
            GR, HR = G - GL, H - HL
            CR = n - CL
            ok = ((CL >= self.min_samples_leaf) & (CR >= self.min_samples_leaf)
                  & (HL > 1e-9) & (HR > 1e-9))
            gain = np.where(ok, GL * GL / (HL + self.l2) + GR * GR / (HR + self.l2) - parent_gain,
                            -np.inf)
            k = int(np.argmax(gain))
            if gain[k] > best_gain:
                best_gain, best_j, best_k = float(gain[k]), int(j), k
        if best_j < 0:
            return {"feat": -1, "thr": -1, "left": -1, "right": -1, "value": leaf}
        mask = B[idx, best_j] <= best_k
        li, ri = idx[mask], idx[~mask]
        if len(li) == 0 or len(ri) == 0:
            return {"feat": -1, "thr": -1, "left": -1, "right": -1, "value": leaf}
        return {"feat": best_j, "thr": best_k,
                "left": self._grow_lr(B, g, h, li, depth + 1, n_feat_try),
                "right": self._grow_lr(B, g, h, ri, depth + 1, n_feat_try),
                "value": leaf}

    def fit(self, X, y, sample_weight=None, verbose=False):
        X = np.asarray(X, float)
        y = np.asarray(y, float)
        w = np.ones(len(y)) if sample_weight is None else np.asarray(sample_weight, float)
        self.edges = self._fit_bins(X)
        B = self._bin(X, self.edges)
        base_rate = float(np.sum(w * y) / max(np.sum(w), 1e-9))
        base_rate = min(max(base_rate, 1e-4), 1 - 1e-4)
        self.base = float(np.log(base_rate / (1 - base_rate)))
        F = np.full(len(y), self.base)
        n_feat_try = max(1, int(round(self.colsample * X.shape[1])))
        self.trees = []
        for m in range(self.n_trees):
            p = self._sigmoid(F)
            g = w * (p - y)
            h = w * p * (1.0 - p)
            h = np.maximum(h, 1e-6)
            if self.subsample < 1.0:
                idx = self.rng.choice(len(y), size=int(self.subsample * len(y)), replace=False)
            else:
                idx = np.arange(len(y))
            node = self._grow_lr(B, g, h, idx, 0, n_feat_try)
            feat, thr, left, right, value = [], [], [], [], []
            self._flatten(node, feat, thr, left, right, value)
            tree = {"feat": np.asarray(feat, np.int32), "thr": np.asarray(thr, np.int32),
                    "left": np.asarray(left, np.int32), "right": np.asarray(right, np.int32),
                    "value": np.asarray(value, np.float64)}
            self.trees.append(tree)
            F += self.learning_rate * self._predict_tree(tree, B)
            if verbose and (m + 1) % 100 == 0:
                print(f"        tree {m+1}/{self.n_trees} train_logloss="
                      f"{logloss(y, self._sigmoid(F), w):.4f}", flush=True)
        return self

    def decision(self, X):
        B = self._bin(np.asarray(X, float), self.edges)
        F = np.full(len(B), self.base)
        for tree in self.trees:
            F += self.learning_rate * self._predict_tree(tree, B)
        return F

    def predict_proba(self, X):
        return self._sigmoid(self.decision(X))


# ═══════════════════════════════════════════════════════════════ metrics
def logloss(y, p, w=None):
    p = np.clip(np.asarray(p, float), 1e-12, 1 - 1e-12)
    y = np.asarray(y, float)
    if w is None:
        w = np.ones(len(y))
    return float(-np.sum(w * (y * np.log(p) + (1 - y) * np.log(1 - p))) / np.sum(w))


def brier(y, p):
    return float(np.mean((np.asarray(p, float) - np.asarray(y, float)) ** 2))


def auc(y, p):
    """Rank-based ROC-AUC (Mann-Whitney U), no sklearn."""
    y = np.asarray(y, int)
    p = np.asarray(p, float)
    n_pos, n_neg = int(y.sum()), int((1 - y).sum())
    if n_pos == 0 or n_neg == 0:
        return float("nan")
    order = np.argsort(p, kind="mergesort")
    ranks = np.empty(len(p), float)
    sp = p[order]
    i = 0
    while i < len(sp):
        j = i
        while j + 1 < len(sp) and sp[j + 1] == sp[i]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2.0 + 1.0
        i = j + 1
    return float((ranks[y == 1].sum() - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg))


def cls_report(y, p, thr):
    y = np.asarray(y, int)
    pred = (np.asarray(p, float) >= thr).astype(int)
    tp = int(((pred == 1) & (y == 1)).sum())
    fp = int(((pred == 1) & (y == 0)).sum())
    fn = int(((pred == 0) & (y == 1)).sum())
    tn = int(((pred == 0) & (y == 0)).sum())
    prec = tp / (tp + fp) if tp + fp else float("nan")
    rec = tp / (tp + fn) if tp + fn else float("nan")
    f1 = 2 * prec * rec / (prec + rec) if (tp + fp) and (tp + fn) and (prec + rec) > 0 else 0.0
    return {
        "threshold": round(float(thr), 4),
        "base_rate_pct": round(100.0 * float(y.mean()), 2),
        "accuracy_pct": round(100.0 * float((pred == y).mean()), 2),
        "precision_pct": None if np.isnan(prec) else round(100 * prec, 2),
        "recall_pct": None if np.isnan(rec) else round(100 * rec, 2),
        "f1": None if np.isnan(f1) else round(f1, 3),
        "brier": round(brier(y, p), 4),
        "auc": None if np.isnan(auc(y, p)) else round(auc(y, p), 3),
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "n": len(y),
    }


def reg_report(y, p, unit=""):
    """Error in the target's own units, plus two percentage views.

    MAPE is reported only over rows where the target is at least 10 % of its mean.
    Both soiling loss and specific yield fall to ~0 on calm/low-sun days, and
    dividing by those makes MAPE explode into meaningless numbers (a previous run
    printed 1.1e11 %); mae_pct_of_mean is the stable headline figure.
    """
    y = np.asarray(y, float)
    p = np.asarray(p, float)
    err = p - y
    mae = float(np.mean(np.abs(err)))
    mean_abs = float(np.mean(np.abs(y)))
    keep = np.abs(y) >= 0.10 * mean_abs if mean_abs > 1e-9 else np.zeros(len(y), bool)
    mape = float(100 * np.mean(np.abs(err[keep]) / np.abs(y[keep]))) if keep.sum() >= 5 else None
    return {
        "n": len(y),
        "mae": round(mae, 4),
        "rmse": round(float(np.sqrt(np.mean(err ** 2))), 4),
        "r2": round(T._r2(y, p), 4),
        "mae_pct_of_mean": round(100 * mae / mean_abs, 2) if mean_abs > 1e-9 else None,
        "mape_pct_where_meaningful": None if mape is None else round(mape, 2),
        "bias": round(float(np.mean(err)), 4),
        "mean_actual": round(float(y.mean()), 4),
        "unit": unit,
    }


def choose_threshold(y, p, grid=None):
    """Pick the operating point that maximises F1 on a validation block.

    Missing a storm is the expensive error for an operator (a crew that never
    came), so if two thresholds tie on F1 the higher-recall one wins.
    """
    y = np.asarray(y, int)
    if y.sum() == 0:
        return 0.5
    grid = grid if grid is not None else np.unique(np.quantile(p, np.linspace(0.5, 0.999, 60)))
    best = (0.5, -1.0, -1.0)
    for thr in grid:
        r = cls_report(y, p, thr)
        f1 = r["f1"] or 0.0
        rec = r["recall_pct"] or 0.0
        if (f1, rec) > (best[1], best[2]):
            best = (float(thr), f1, rec)
    return best[0]


# ═══════════════════════════════════════════════════════════════ dataset
def load_rows(path=CSV_PATH):
    """data/ai/daily.csv -> {site_id: [row dicts sorted by date]}"""
    import csv as _csv
    if not os.path.exists(path):
        raise SystemExit(f"missing {path} — run the harvest first")
    by_site = {}
    with open(path, newline="") as fh:
        for r in _csv.DictReader(fh):
            r["doy"] = float(datetime.strptime(r["date"], "%Y-%m-%d").timetuple().tm_yday)
            by_site.setdefault(r["site"], []).append(r)
    for s in by_site:
        by_site[s].sort(key=lambda x: x["date"])
    return by_site


def make_samples(by_site, warmup=45):
    """Rows of (features@t, targets@t+1..t+3, date, site).

    The storm threshold is per site (3x that site's median PM10, floored at 300)
    and is computed from the TRAIN block only, so the test period cannot influence
    even the label definition. Returns (samples, thresholds).
    """
    samples = []
    thresholds = {}
    for site, rows in by_site.items():
        train_rows = [r for r in rows if r["date"] < VAL_START] or rows
        thr = F.site_storm_threshold([r.get("pm10_max") for r in train_rows])
        thresholds[site] = round(thr, 1)
        for i in range(warmup, len(rows) - 3):
            f = F.build_features(rows, i, storm_thr=thr)
            if not f:
                continue
            s1 = F.label_soiling(rows, i + 1)
            s2 = F.label_soiling(rows, i + 2)
            s3 = F.label_soiling(rows, i + 3)
            samples.append({
                "site": site, "date": rows[i]["date"],
                "x": f, "thr": thr,
                "storm_t1": F.label_storm(rows[i + 1], thr),
                "storm_t2": F.label_storm(rows[i + 2], thr),
                "storm_t3": F.label_storm(rows[i + 3], thr),
                "yield_t1": F.label_yield(rows[i + 1], s1),
                "ghi_t1": F._f(rows[i + 1].get("ghi_mj_m2")) / 3.6,
                "soiling_t1": s1,
                "pm10_t1": F._f(rows[i + 1].get("pm10_max")),
                "pm10_today": F._f(rows[i].get("pm10_max")),
                "storm_today": F.label_storm(rows[i], thr),
            })
    samples.sort(key=lambda s: (s["date"], s["site"]))
    return samples, thresholds


def to_xy(samples):
    X = np.array([[s["x"][k] for k in F.FEATURES] for s in samples], float)
    return X


def zscore(Xtr, Xte):
    mu = Xtr.mean(axis=0)
    sd = Xtr.std(axis=0)
    sd[sd < 1e-9] = 1.0
    return (Xtr - mu) / sd, (Xte - mu) / sd, mu, sd


# ═══════════════════════════════════════════════════════════════ training
def fit_yield(samples, tr_idx, seed=0, verbose=False):
    X = to_xy(samples)
    y = np.array([s["yield_t1"] for s in samples], float)
    g = T.GBRT(n_trees=300, max_depth=4, learning_rate=0.05, min_samples_leaf=25, seed=seed)
    g.fit(X[tr_idx], y[tr_idx], verbose=verbose)
    Xtr, Xall, mu, sd = zscore(X[tr_idx], X)
    m = T.MLP(n_in=X.shape[1], hidden=(64, 32), n_out=1, lr=3e-3, epochs=120, batch=128, seed=seed)
    m.fit(Xtr, y[tr_idx][:, None] / max(y[tr_idx].mean(), 1e-6))
    scale = max(y[tr_idx].mean(), 1e-6)
    mdl = {"gbrt": g, "mlp": m, "mu": mu, "sd": sd, "scale": scale}
    inner = tr_idx[int(len(tr_idx) * 0.85):]
    if len(inner) >= 40:
        pr = predict_yield(mdl, X[inner])
        mdl["w"] = blend_weights(y[inner], pr["gbrt"], pr["mlp"])
    return mdl, X, y


def blend_weights(y_val, p_gb_val, p_mlp_val):
    """Inverse-error weights so the ensemble can never be worse than the weaker
    member by construction. Falls back to a 50/50 split if either is perfect."""
    eg = float(np.mean(np.abs(np.asarray(p_gb_val) - np.asarray(y_val))))
    em = float(np.mean(np.abs(np.asarray(p_mlp_val) - np.asarray(y_val))))
    if eg <= 1e-9 and em <= 1e-9:
        return 0.5, 0.5
    wg, wm = 1.0 / max(eg, 1e-9), 1.0 / max(em, 1e-9)
    s = wg + wm
    return wg / s, wm / s


def combine(p_gb, p_mlp, w):
    wg, wm = w
    return wg * np.asarray(p_gb) + wm * np.asarray(p_mlp)


def predict_yield(mdl, X):
    Xs = (X - mdl["mu"]) / mdl["sd"]
    p_mlp = mdl["mlp"].predict(Xs)[:, 0] * mdl["scale"]
    p_gb = mdl["gbrt"].predict(X)
    return {"gbrt": p_gb, "mlp": p_mlp, "ensemble": combine(p_gb, p_mlp, mdl.get("w", (0.5, 0.5)))}


def fit_soiling(samples, tr_idx, seed=0):
    X = to_xy(samples)
    y = np.array([s["soiling_t1"] for s in samples], float)
    g = T.GBRT(n_trees=280, max_depth=4, learning_rate=0.05, min_samples_leaf=25, seed=seed)
    g.fit(X[tr_idx], y[tr_idx])
    Xtr, _, mu, sd = zscore(X[tr_idx], X)
    m = T.MLP(n_in=X.shape[1], hidden=(64, 32), n_out=1, lr=3e-3, epochs=120, batch=128, seed=seed)
    m.fit(Xtr, y[tr_idx][:, None] / 50.0)          # soiling % is 0..~60; scale it
    mdl = {"gbrt": g, "mlp": m, "mu": mu, "sd": sd, "scale": 50.0}
    inner = tr_idx[int(len(tr_idx) * 0.85):]
    if len(inner) >= 40:
        pr = predict_soiling(mdl, X[inner])
        mdl["w"] = blend_weights(y[inner], pr["gbrt"], pr["mlp"])
    return mdl, X, y


def predict_soiling(mdl, X):
    Xs = (X - mdl["mu"]) / mdl["sd"]
    p_mlp = mdl["mlp"].predict(Xs)[:, 0] * mdl["scale"]
    p_gb = mdl["gbrt"].predict(X)
    return {"gbrt": p_gb, "mlp": p_mlp, "ensemble": combine(p_gb, p_mlp, mdl.get("w", (0.5, 0.5)))}


def fit_storm(samples, horizon, tr_idx, seed=0, verbose=False):
    X = to_xy(samples)
    y = np.array([s[f"storm_t{horizon}"] for s in samples], float)
    clf = GBRTClassifier(n_trees=320, max_depth=3, learning_rate=0.07, min_samples_leaf=25,
                         seed=seed)
    clf.fit(X[tr_idx], y[tr_idx], verbose=verbose)
    Xtr, _, mu, sd = zscore(X[tr_idx], X)
    m = T.MLP(n_in=X.shape[1], hidden=(64, 32), n_out=1, lr=3e-3, epochs=120, batch=128, seed=seed)
    m.fit(Xtr, y[tr_idx][:, None])
    mdl = {"clf": clf, "mlp": m, "mu": mu, "sd": sd}
    inner = tr_idx[int(len(tr_idx) * 0.85):]
    if len(inner) >= 40:
        pr = predict_storm(mdl, X[inner])
        mdl["w"] = blend_weights(y[inner], pr["gbrt"], pr["mlp"])
    return mdl, X, y


def predict_storm(mdl, X):
    Xs = (X - mdl["mu"]) / mdl["sd"]
    p_mlp = np.clip(mdl["mlp"].predict(Xs)[:, 0], 0.0, 1.0)
    p_gb = mdl["clf"].predict_proba(X)
    return {"gbrt": p_gb, "mlp": p_mlp, "ensemble": combine(p_gb, p_mlp, mdl.get("w", (0.5, 0.5)))}


# ═══════════════════════════════════════════════════════════════ save / load
def save_bundle(path, kind, models, extra=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    z = {"kind": np.array(kind)}
    def put(prefix, model):
        for attr in ("learning_rate", "l2", "max_depth"):
            if hasattr(model, attr):
                z[f"{prefix}_{attr}"] = np.array([float(getattr(model, attr))])
        for attr in ("edges", "trees", "base", "W", "b"):
            if hasattr(model, attr):
                v = getattr(model, attr)
                if attr == "edges":
                    for j, e in enumerate(v):
                        z[f"{prefix}_edge_{j}"] = np.asarray(e, float)
                    z[f"{prefix}_n_edge"] = np.array(len(v))
                elif attr == "trees":
                    for m, tr in enumerate(v):
                        for k, arr in tr.items():
                            z[f"{prefix}_t{m}_{k}"] = arr
                    z[f"{prefix}_n_trees"] = np.array(len(v))
                elif attr == "base":
                    z[f"{prefix}_base"] = np.array([v], float)
                else:
                    for i, arr in enumerate(v):
                        z[f"{prefix}_W{i}" if attr == "W" else f"{prefix}_b{i}"] = arr
                    z[f"{prefix}_n_{attr}"] = np.array(len(v))
    if "gbrt" in models:
        put("gbrt", models["gbrt"])
    if "clf" in models:
        put("clf", models["clf"])
    if "mlp" in models:
        put("mlp", models["mlp"])
    for k in ("mu", "sd", "scale", "w"):
        if k in models:
            z[k] = np.asarray(models[k], float)
    z["meta_json"] = np.array(json.dumps(extra or {}))
    np.savez_compressed(path, **z)
    return path


# ═══════════════════════════════════════════════════════════════ main
def main():
    global CSV_PATH, OUT_DIR, METRICS_PATH
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="skip leave-one-site-out")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--csv", default=CSV_PATH, help="training CSV (default data/ai/daily.csv)")
    ap.add_argument("--out", default=OUT_DIR, help="model output directory")
    args = ap.parse_args()
    CSV_PATH, OUT_DIR = args.csv, args.out
    METRICS_PATH = os.path.join(OUT_DIR, "metrics.json")

    t0 = time.time()
    CSV_PATH = os.environ.get("SOLARGUARD_AI_CSV", CSV_PATH) if "--csv" not in sys.argv else CSV_PATH
    by_site = load_rows(CSV_PATH)
    n_days = sum(len(v) for v in by_site.values())
    print(f"loaded {len(by_site)} sites, {n_days} site-days from {CSV_PATH}")
    samples, thresholds = make_samples(by_site)
    pos = sum(s["storm_t1"] for s in samples)
    print(f"built {len(samples)} samples "
          f"({samples[0]['date']} .. {samples[-1]['date']})")
    print(f"storm days in the target: {pos} ({100 * pos / len(samples):.1f} %)")
    print("per-site storm thresholds (3x median PM10, floor 300): "
          + ", ".join(f"{k} {v:.0f}" for k, v in sorted(thresholds.items())) + "\n")
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, "site_thresholds.json"), "w") as fh:
        json.dump(thresholds, fh, indent=1)

    dates = np.array([s["date"] for s in samples])
    tr = np.where(dates < VAL_START)[0]
    va = np.where((dates >= VAL_START) & (dates < TEST_START))[0]
    te = np.where(dates >= TEST_START)[0]
    print(f"split: train {len(tr)} | val {len(va)} | test {len(te)} "
          f"(train < {VAL_START} <= val < {TEST_START} <= test)\n")

    out = {"generated_utc": datetime.utcnow().isoformat(timespec="seconds") + "Z",
           "features": F.FEATURES, "n_features": len(F.FEATURES),
           "n_samples": len(samples), "n_sites": len(by_site),
           "date_range": [samples[0]["date"], samples[-1]["date"]],
           "splits": {"train": len(tr), "val": len(va), "test": len(te)},
           "storm_definition": (f"daily max PM10 >= max({F.STORM_MULT:g} x the site's median, "
                                f"{F.STORM_FLOOR:g} ug/m3) — a per-site definition; "
                                f"thresholds in site_thresholds.json"),
           "storm_thresholds": thresholds,
           "storm_base_rate_pct": round(100 * pos / len(samples), 2),
           "classifier": {}, "regressors": {}}

    # ---------------------------------------------------------------- storms
    print("── sandstorm probability (t+1, t+2, t+3) ─────────────────────────")
    for h in (1, 2, 3):
        mdl, X, y = fit_storm(samples, h, tr, verbose=args.verbose)
        pv = predict_storm(mdl, X[va])["ensemble"]
        pt = predict_storm(mdl, X[te])["ensemble"]
        thr = choose_threshold(y[va], pv)
        # persistence baseline: tomorrow looks like today
        persist = np.array([s["storm_today"] for s in samples], float)
        res = {
            "val": cls_report(y[va], pv, thr),
            "test_tuned": cls_report(y[te], pt, thr),
            "test_at_0.5": cls_report(y[te], pt, 0.5),
            "baseline_persistence": cls_report(y[te], persist[te], 0.5),
            "baseline_climatology_brier": round(float(y[te].mean() * (1 - y[te].mean())), 4),
        }
        out["classifier"][f"storm_t{h}"] = res
        save_bundle(os.path.join(OUT_DIR, f"storm_t{h}.npz"), "storm", mdl,
                    {"horizon": h, "features": F.FEATURES, "threshold": thr,
                     "storm_definition": (f"PM10 >= max({F.STORM_MULT:g} x site median, "
                                          f"{F.STORM_FLOOR:g})"),
                     "blend_weights": list(mdl.get("w", (0.5, 0.5)))})
        print(f"  day+{h}: threshold {thr:.3f} | TEST recall {(res['test_tuned']['recall_pct'] or 0):.1f}% "
              f"precision {(res['test_tuned']['precision_pct'] or 0):.1f}% "
              f"AUC {res['test_tuned']['auc']} Brier {res['test_tuned']['brier']} "
              f"(climatology {res['baseline_climatology_brier']}) | "
              f"persistence F1 {res['baseline_persistence']['f1']}")

    # ---------------------------------------------------------------- yield
    print("\n── panel output (kWh/kWp for t+1) ────────────────────────────────")
    ym, X, y = fit_yield(samples, tr)
    yp = predict_yield(ym, X)
    # persistence baseline: yesterday's irradiance carried forward
    prev_yield = np.array([s["x"]["ghi_mj_m2"] / 3.6 * F.PERF_RATIO_CLEAN for s in samples])
    out["regressors"]["yield_t1"] = {
        "gbrt": reg_report(y[te], yp["gbrt"][te], "kWh/kWp"),
        "mlp": reg_report(y[te], yp["mlp"][te], "kWh/kWp"),
        "ensemble": reg_report(y[te], yp["ensemble"][te], "kWh/kWp"),
        "val_ensemble": reg_report(y[va], yp["ensemble"][va], "kWh/kWp"),
        "baseline_persistence_yesterdays_irradiance":
            reg_report(y[te], prev_yield[te], "kWh/kWp"),
        "baseline_mean": reg_report(y[te], np.full(len(te), y[tr].mean()), "kWh/kWp"),
    }
    save_bundle(os.path.join(OUT_DIR, "yield_t1.npz"), "yield", ym,
                {"features": F.FEATURES, "unit": "kWh/kWp/day",
                 "blend_weights": list(ym.get("w", (0.5, 0.5)))})
    e = out["regressors"]["yield_t1"]["ensemble"]
    print(f"  GBRT     MAE {out['regressors']['yield_t1']['gbrt']['mae']:.3f} "
          f"R2 {out['regressors']['yield_t1']['gbrt']['r2']:.3f}")
    print(f"  MLP      MAE {out['regressors']['yield_t1']['mlp']['mae']:.3f} "
          f"R2 {out['regressors']['yield_t1']['mlp']['r2']:.3f}")
    print(f"  ENSEMBLE ({len(ym.get('w', (0.5, 0.5))) and ym['w'][0]:.2f}·GBRT + {ym['w'][1]:.2f}·MLP) "
          f"MAE {e['mae']:.3f} kWh/kWp = {e['mae_pct_of_mean']:.1f}% of the mean, "
          f"RMSE {e['rmse']:.3f}, R2 {e['r2']:.3f}")
    print(f"  baseline yesterday's irradiance MAE "
          f"{out['regressors']['yield_t1']['baseline_persistence_yesterdays_irradiance']['mae']:.3f}")

    # -------------------------------------------------------------- soiling
    print("\n── soiling loss (t+1) ────────────────────────────────────────────")
    sm, X, y = fit_soiling(samples, tr)
    sp = predict_soiling(sm, X)
    out["regressors"]["soiling_t1"] = {
        "gbrt": reg_report(y[te], sp["gbrt"][te], "% loss"),
        "mlp": reg_report(y[te], sp["mlp"][te], "% loss"),
        "ensemble": reg_report(y[te], sp["ensemble"][te], "% loss"),
        "mean_actual_pct": round(float(y[te].mean()), 3),
        "baseline_mean": reg_report(y[te], np.full(len(te), y[tr].mean()), "% loss"),
    }
    save_bundle(os.path.join(OUT_DIR, "soiling_t1.npz"), "soiling", sm,
                {"features": F.FEATURES, "unit": "% optical loss",
                 "blend_weights": list(sm.get("w", (0.5, 0.5)))})
    s = out["regressors"]["soiling_t1"]["ensemble"]
    print(f"  ENSEMBLE MAE {s['mae']:.3f} points ({s['mae_pct_of_mean']:.1f}% of the mean), "
          f"R2 {s['r2']:.3f} | baseline(mean) MAE "
          f"{out['regressors']['soiling_t1']['baseline_mean']['mae']:.3f}")

    # ------------------------------------------------------------------ loso
    if not args.quick:
        print("\n── leave-one-site-out (generalisation to an unseen site) ─────────")
        loso = {}
        sites = sorted(by_site)
        for hold in sites:
            tr_idx = np.array([i for i, s in enumerate(samples)
                               if s["site"] != hold and s["date"] < VAL_START])
            te_idx = np.array([i for i, s in enumerate(samples)
                               if s["site"] == hold and s["date"] >= VAL_START])
            if len(tr_idx) < 200 or len(te_idx) < 50:
                continue
            row = {}
            Xi = to_xy(samples)
            # storms
            for h in (1, 2):
                mdl, X, y = fit_storm(samples, h, tr_idx)
                p = predict_storm(mdl, X[te_idx])["ensemble"]
                row[f"storm_t{h}"] = cls_report(y[te_idx], p, 0.5)
            ym2, X, yv = fit_yield(samples, tr_idx)
            row["yield_t1"] = reg_report(yv[te_idx], predict_yield(ym2, X[te_idx])["ensemble"], "kWh/kWp")
            sm2, X, ys = fit_soiling(samples, tr_idx)
            row["soiling_t1"] = reg_report(ys[te_idx], predict_soiling(sm2, X[te_idx])["ensemble"], "%")
            loso[hold] = {"n_test": len(te_idx), **row}
            print(f"  hold-out {hold:<10} n={len(te_idx):>4} | "
                  f"yield MAE {row['yield_t1']['mae']:.3f} R2 {row['yield_t1']['r2']:.3f} | "
                  f"soiling MAE {row['soiling_t1']['mae']:.3f} | "
                  f"storm@+1 AUC {row['storm_t1']['auc']}")
        if loso:
            out["leave_one_site_out"] = loso
            out["leave_one_site_out_mean"] = {
                "yield_mae": round(float(np.mean([v["yield_t1"]["mae"] for v in loso.values()])), 4),
                "yield_r2": round(float(np.mean([v["yield_t1"]["r2"] for v in loso.values()])), 4),
                "soiling_mae": round(float(np.mean([v["soiling_t1"]["mae"] for v in loso.values()])), 4),
                "storm_t1_auc_mean": round(float(np.nanmean(
                    [v["storm_t1"]["auc"] or np.nan for v in loso.values()])), 3),
                "storm_t2_auc_mean": round(float(np.nanmean(
                    [v["storm_t2"]["auc"] or np.nan for v in loso.values()])), 3),
            }
            m = out["leave_one_site_out_mean"]
            print(f"  mean: yield MAE {m['yield_mae']:.3f} (R2 {m['yield_r2']:.3f}) | "
                  f"soiling MAE {m['soiling_mae']:.3f} | storm AUC {m['storm_t1_auc_mean']}")

    out["train_seconds"] = round(time.time() - t0, 1)
    with open(METRICS_PATH, "w") as fh:
        json.dump(out, fh, indent=2)
    print(f"\nsaved {OUT_DIR}/*.npz + {METRICS_PATH}  ({out['train_seconds']}s)")


if __name__ == "__main__":
    main()

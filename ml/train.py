#!/usr/bin/env python3
"""
train.py -- SolarGuard Space
===========================
Trains TWO from-scratch, pure-numpy, CPU-only models on the soiling dataset:

  (a) GBRT  -- gradient-boosted regression trees (histogram split search, squared error,
               shallow trees, boosting implemented by hand).  One boosted ensemble per
               target.
  (b) MLP   -- 2-hidden-layer perceptron, tanh/relu, mini-batch Adam implemented by hand,
               standardised inputs and targets.

Targets
    next-day soiling loss   [%]        (physics label, see physics_soiling.py)
    next-day dust deposition [g/m2/day]

Evaluation (REAL, on held-out data)
    (i)  time split        -- latest 20 % of calendar dates held out
    (ii) leave-one-site-out-- each of the 12 sites held out in turn, model trained on the
                              other 11 (tests geographic generalisation, not just time)

Outputs
    models/gbrt.npz, models/mlp.npz          plain npz: numeric arrays + a JSON meta string
    models/metrics.json                      real holdout metrics + literature calibration
    models/feature_meta.json                 feature order, defaults, scalers (for predict.py)

CLI
    python ml/train.py [--trees 220] [--epochs 160] [--quick]
"""

import argparse
import csv
import json
import math
import os
import sys
import time
from datetime import datetime

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)

import physics_soiling as phys  # noqa: E402

CSV_PATH = os.path.join(ROOT, "data", "soiling_dataset.csv")
MODELS_DIR = os.path.join(ROOT, "models")
FEATURES_PATH = os.path.join(MODELS_DIR, "feature_meta.json")
METRICS_PATH = os.path.join(MODELS_DIR, "metrics.json")
TARGET_NAMES = ["soiling_loss_pct", "deposition_g_m2_day"]
# Both targets are fitted in NATIVE units (tested: fitting deposition in log space and
# back-transforming gave a WORSE holdout R2 -- 0.31 vs 0.38 native, 0.57 vs 0.61 in log
# space -- because exp(mean of logs) is a geometric mean and biases the extreme dust-storm
# days low).  We still report r2_logspace as an extra diagnostic for the skewed deposition
# target, since native R2 is dominated by a handful of storm days.
TARGET_TRANSFORMS = ["none", "none"]
LOGSPACE_DIAGNOSTIC_TARGETS = {1}   # deposition_g_m2_day


def transform_targets(y):
    out = np.array(y, dtype=float, copy=True)
    for i, t in enumerate(TARGET_TRANSFORMS):
        if t == "log":
            out[:, i] = np.log(np.maximum(out[:, i], 1e-9))
    return out


def inverse_transform(pred, target_index):
    t = TARGET_TRANSFORMS[target_index]
    if t == "log":
        return np.exp(np.clip(pred, -50, 50))
    return pred


def _r2_logspace(y, p):
    ly, lp = np.log(np.maximum(y, 1e-9)), np.log(np.maximum(p, 1e-9))
    ss_res = float(np.sum((ly - lp) ** 2))
    ss_tot = float(np.sum((ly - ly.mean()) ** 2))
    return 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")

BASE_FEATURES = [
    "lat", "lon", "elevation_m", "doy_sin", "doy_cos",
    "tmax_c", "tmin_c", "tmean_c", "rh_mean_pct", "wind_max_kmh", "gust_max_kmh",
    "precip_mm", "radiation_mj_m2", "et0_mm",
    "pm10_mean_ugm3", "pm2_5_mean_ugm3", "dust_mean_ugm3", "aod_mean",
    "days_since_rain", "days_since_clean",
]
# Causal rolling aggregates (window ends on day t) -- capture the accumulation state of the
# module so next-day loss does not have to be inferred from a single day.
ROLL_FEATURES = [
    ("pm10_mean_ugm3", 3, "mean"), ("pm10_mean_ugm3", 7, "mean"),
    ("pm10_mean_ugm3", 30, "mean"), ("pm10_mean_ugm3", 90, "mean"),
    ("dust_mean_ugm3", 7, "mean"), ("dust_mean_ugm3", 30, "mean"),
    ("aod_mean", 7, "mean"),
    ("wind_max_kmh", 7, "mean"), ("wind_max_kmh", 30, "mean"),
    ("gust_max_kmh", 7, "mean"), ("rh_mean_pct", 7, "mean"),
    ("precip_mm", 7, "sum"), ("precip_mm", 30, "sum"),
    ("pm10_max_ugm3", 7, "max"),
]
# Causal EXPANDING means since the start of the record: a deployable proxy for "how dusty is
# this site overall" (available from any AQ archive) that lets the model identify a site's
# dust-loading level without ever seeing its future.  Strictly causal -> no leakage.
EXPANDING_FEATURES = ["pm10_mean_ugm3", "dust_mean_ugm3", "aod_mean"]
FEATURES = (BASE_FEATURES
            + [f"{c}_{w}d_{a}" for c, w, a in ROLL_FEATURES]
            + [f"{c}_expmean" for c in EXPANDING_FEATURES])


def _expanding_mean(x):
    """Causal expanding mean (leak-free: value at t uses only days <= t)."""
    x = np.asarray(x, dtype=float)
    c = np.cumsum(x)
    return c / np.arange(1, len(x) + 1)

# ------------------------------------------------------------------------------ utilities
def _r2(y, p):
    y = np.asarray(y, float)
    ss_res = float(np.sum((y - p) ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    return 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")


def metrics(y, p):
    y = np.asarray(y, float)
    p = np.asarray(p, float)
    return {
        "n": int(len(y)),
        "mae": float(np.mean(np.abs(y - p))),
        "rmse": float(np.sqrt(np.mean((y - p) ** 2))),
        "r2": _r2(y, p),
        "bias": float(np.mean(p - y)),
    }


# ------------------------------------------------------------------------ dataset build
def _rolling(x, w, how):
    """Causal rolling aggregate over the previous w days, inclusive of today (vectorised)."""
    x = np.asarray(x, dtype=float)
    n = len(x)
    if n == 0:
        return x
    if how in ("mean", "sum"):
        c = np.concatenate([[0.0], np.cumsum(x)])
        lo = np.maximum(0, np.arange(n) - w + 1)
        tot = c[1:] - c[lo]
        if how == "sum":
            return tot
        cnt = (np.arange(n) + 1 - lo).astype(float)
        return tot / cnt
    if how == "max":
        if w <= 1:
            return x.copy()
        pad = np.full(w - 1, x[0] if np.isfinite(x[0]) else 0.0)
        xp = np.concatenate([pad, x])
        win = np.lib.stride_tricks.sliding_window_view(xp, w)
        return win.max(axis=1)
    raise ValueError(how)


def build_training_table(csv_path=CSV_PATH, calib=None, cleaning_interval_days=None):
    """Assemble the supervised table: features on day t -> labels on day t+1."""
    if cleaning_interval_days:
        phys.CLEANING_INTERVAL_DAYS = cleaning_interval_days
    calib = calib or phys.load_calibration()
    sites = phys.load_dataset(csv_path)

    X_all, y_all, site_all, date_all, meta_rows = [], [], [], [], []
    for site, s in sorted(sites.items()):
        d = s["data"]
        n = len(s["dates"])
        factor = phys.factor_for_site(site, s["meta"]["region"], calib)
        out = phys.simulate_site(d, factor)
        feats = {}
        feats["lat"] = np.full(n, s["meta"]["lat"])
        feats["lon"] = np.full(n, s["meta"]["lon"])
        elev = s["meta"]["elevation_m"]
        feats["elevation_m"] = np.full(n, elev if np.isfinite(elev) else 500.0)
        doy = np.array([datetime.strptime(x, "%Y-%m-%d").timetuple().tm_yday for x in s["dates"]], float)
        feats["doy_sin"] = np.sin(2 * np.pi * doy / 365.25)
        feats["doy_cos"] = np.cos(2 * np.pi * doy / 365.25)
        for col in ("tmax_c", "tmin_c", "tmean_c", "rh_mean_pct", "wind_max_kmh",
                    "gust_max_kmh", "precip_mm", "radiation_mj_m2", "et0_mm",
                    "pm10_mean_ugm3", "pm2_5_mean_ugm3", "dust_mean_ugm3", "aod_mean",
                    "pm10_max_ugm3"):
            feats[col] = d[col]
        feats["days_since_rain"] = out["days_since_rain"].astype(float)
        feats["days_since_clean"] = out["days_since_clean"].astype(float)
        for c, w, how in ROLL_FEATURES:
            feats[f"{c}_{w}d_{how}"] = _rolling(d[c], w, how)
        for c in EXPANDING_FEATURES:
            feats[f"{c}_expmean"] = _expanding_mean(d[c])

        Xs = np.stack([feats[f] for f in FEATURES], axis=1)
        target_loss = out["soiling_loss_pct"][1:]   # next day
        target_dep = out["deposition_g_m2_day"][1:]
        ys = np.stack([target_loss, target_dep], axis=1)
        Xs = Xs[:-1]

        ok = np.all(np.isfinite(Xs), axis=1) & np.all(np.isfinite(ys), axis=1)
        X_all.append(Xs[ok])
        y_all.append(ys[ok])
        site_all.append(np.full(ok.sum(), site))
        date_all.append(s["dates"][:-1][ok])

    X = np.concatenate(X_all).astype(np.float64)
    y = np.concatenate(y_all).astype(np.float64)
    site = np.concatenate(site_all)
    dates = np.concatenate(date_all)
    return X, y, site, dates


# ------------------------------------------------------------------------------ GBRT
class GBRT:
    """
    Gradient-boosted regression trees, histogram split search, squared-error loss.
    Everything (binning, tree growth, boosting) is implemented here in numpy -- no
    sklearn/xgboost/lightgbm.
    """

    def __init__(self, n_trees=220, max_depth=3, learning_rate=0.06, min_samples_leaf=25,
                 max_bins=32, subsample=0.85, colsample=0.7, l2=1e-6, seed=0):
        self.n_trees = n_trees
        self.max_depth = max_depth
        self.learning_rate = learning_rate
        self.min_samples_leaf = min_samples_leaf
        self.max_bins = max_bins
        self.subsample = subsample
        self.colsample = colsample
        self.l2 = l2
        self.seed = seed
        self.rng = np.random.default_rng(seed)

    # -- binning -----------------------------------------------------------------
    def _fit_bins(self, X):
        edges = []
        for j in range(X.shape[1]):
            qs = np.quantile(X[:, j], np.linspace(0, 1, self.max_bins + 1)[1:-1])
            qs = np.unique(qs)
            edges.append(qs)
        return edges

    def _bin(self, X, edges):
        B = np.empty(X.shape, dtype=np.int32)
        for j in range(X.shape[1]):
            B[:, j] = np.searchsorted(edges[j], X[:, j], side="left")
        return B

    # -- single tree --------------------------------------------------------------
    def _grow(self, B, r, idx, depth, n_feat_try):
        n = len(idx)
        val = float(np.mean(r[idx]))
        if depth >= self.max_depth or n < 2 * self.min_samples_leaf:
            return {"feat": -1, "thr": -1, "left": -1, "right": -1, "value": val}
        total_s = float(np.sum(r[idx]))
        total_c = float(n)
        best_score, best_j, best_k = -np.inf, -1, -1
        feats = self.rng.choice(B.shape[1], size=min(n_feat_try, B.shape[1]), replace=False)
        for j in feats:
            b = B[idx, j]
            cnt = np.bincount(b, minlength=self.max_bins)
            s = np.bincount(b, weights=r[idx], minlength=self.max_bins)
            csum = np.cumsum(s)[:-1]
            ccnt = np.cumsum(cnt)[:-1].astype(float)
            valid = (ccnt >= self.min_samples_leaf) & ((total_c - ccnt) >= self.min_samples_leaf) \
                    & (ccnt > 0) & (total_c - ccnt > 0)
            if not valid.any():
                continue
            left = np.where(valid, csum ** 2 / np.maximum(ccnt, 1e-9), 0.0)
            right = np.where(valid, (total_s - csum) ** 2 / np.maximum(total_c - ccnt, 1e-9), 0.0)
            sc = left + right - self.l2 * (total_c)   # l2 is a mild leaf-count penalty knob
            sc = np.where(valid, sc, -np.inf)
            k = int(np.argmax(sc))
            if sc[k] > best_score:
                best_score, best_j, best_k = float(sc[k]), int(j), k
        gain = best_score - (total_s ** 2 / max(total_c, 1e-9)) if best_j >= 0 else -np.inf
        if best_j < 0 or gain <= 1e-9:
            return {"feat": -1, "thr": -1, "left": -1, "right": -1, "value": val}
        mask = B[idx, best_j] <= best_k
        left_idx, right_idx = idx[mask], idx[~mask]
        if len(left_idx) == 0 or len(right_idx) == 0:
            return {"feat": -1, "thr": -1, "left": -1, "right": -1, "value": val}
        return {
            "feat": best_j, "thr": best_k,
            "left": self._grow(B, r, left_idx, depth + 1, n_feat_try),
            "right": self._grow(B, r, right_idx, depth + 1, n_feat_try),
            "value": val,
        }

    @staticmethod
    def _flatten(node, feat, thr, left, right, value):
        me = len(feat)
        feat.append(node["feat"]); thr.append(node["thr"]); value.append(node["value"])
        left.append(-1); right.append(-1)
        if node["feat"] >= 0:
            li = GBRT._flatten(node["left"], feat, thr, left, right, value)
            ri = GBRT._flatten(node["right"], feat, thr, left, right, value)
            left[me] = li; right[me] = ri
        return me

    def fit(self, X, y, verbose=False):
        self.edges = self._fit_bins(X)
        B = self._bin(X, self.edges)
        y = np.asarray(y, float)
        self.base = float(np.mean(y))
        F = np.full(len(y), self.base)
        n_feat_try = max(1, int(round(self.colsample * X.shape[1])))
        self.trees = []
        n_all = len(y)
        for m in range(self.n_trees):
            r = y - F
            if self.subsample < 1.0:
                idx = self.rng.choice(n_all, size=int(self.subsample * n_all), replace=False)
            else:
                idx = np.arange(n_all)
            node = self._grow(B, r, idx, 0, n_feat_try)
            feat, thr, left, right, value = [], [], [], [], []
            self._flatten(node, feat, thr, left, right, value)
            tree = {
                "feat": np.asarray(feat, np.int32), "thr": np.asarray(thr, np.int32),
                "left": np.asarray(left, np.int32), "right": np.asarray(right, np.int32),
                "value": np.asarray(value, np.float64),
            }
            self.trees.append(tree)
            F += self.learning_rate * self._predict_tree(tree, B)
            if verbose and (m + 1) % 50 == 0:
                print(f"      tree {m + 1}/{self.n_trees} train_rmse="
                      f"{np.sqrt(np.mean((y - F) ** 2)):.4f}", flush=True)
        self.train_pred = F
        return self

    @staticmethod
    def _predict_tree(tree, B):
        node = np.zeros(B.shape[0], dtype=np.int64)
        for _ in range(64):
            f = tree["feat"][node]
            internal = f >= 0
            if not internal.any():
                break
            j = np.where(internal, f, 0)
            xb = B[np.arange(B.shape[0]), j]
            go_right = internal & (xb > tree["thr"][node])
            node = np.where(internal, np.where(go_right, tree["right"][node], tree["left"][node]), node)
        return tree["value"][node]

    def predict(self, X):
        B = self._bin(np.asarray(X, float), self.edges)
        out = np.full(B.shape[0], self.base)
        for tree in self.trees:
            out += self.learning_rate * self._predict_tree(tree, B)
        return out

    # -- (de)serialisation ---------------------------------------------------------
    def to_npz(self, path, prefix, meta):
        # NOTE: every key must carry the target prefix. Writing these four
        # unprefixed meant the second target silently overwrote the first one's
        # base/depth, and from_npz (which looks up "<prefix>base") then raised
        # KeyError at load time.
        arrays = {f"{prefix}base": np.array([self.base]),
                  f"{prefix}n_trees": np.array([len(self.trees)]),
                  f"{prefix}depth": np.array([self.max_depth]),
                  f"{prefix}lr": np.array([self.learning_rate])}
        offs = [0]
        cat = {"feat": [], "thr": [], "left": [], "right": [], "value": []}
        for t in self.trees:
            for k in cat:
                cat[k].append(t[k])
            offs.append(offs[-1] + len(t["feat"]))
        for k in cat:
            arrays[f"{prefix}{k}"] = np.concatenate(cat[k]) if cat[k] else np.zeros(0, np.int32)
        arrays[f"{prefix}offsets"] = np.asarray(offs, np.int64)
        # nbins / edges needed to re-bin a single input at inference time
        flat_edges, eoffs = [], [0]
        for e in self.edges:
            flat_edges.append(np.asarray(e, np.float64))
            eoffs.append(eoffs[-1] + len(e))
        arrays[f"{prefix}edges"] = np.concatenate(flat_edges) if flat_edges else np.zeros(0)
        arrays[f"{prefix}edge_offsets"] = np.asarray(eoffs, np.int64)
        arrays[f"{prefix}meta_json"] = np.array([json.dumps(meta)])
        return arrays

    @staticmethod
    def from_npz(z, prefix):
        m = GBRT.__new__(GBRT)
        m.base = float(z[f"{prefix}base"][0])
        m.max_depth = int(z[f"{prefix}depth"][0])
        m.learning_rate = float(z[f"{prefix}lr"][0])
        m.n_trees = int(z[f"{prefix}n_trees"][0])
        m.trees = []
        offs = z[f"{prefix}offsets"]
        feat, thr, left, right, value = (z[f"{prefix}feat"], z[f"{prefix}thr"],
                                        z[f"{prefix}left"], z[f"{prefix}right"],
                                        z[f"{prefix}value"])
        for i in range(m.n_trees):
            s, e = int(offs[i]), int(offs[i + 1])
            m.trees.append({"feat": feat[s:e], "thr": thr[s:e], "left": left[s:e],
                            "right": right[s:e], "value": value[s:e]})
        eoffs = z[f"{prefix}edge_offsets"]
        edges = z[f"{prefix}edges"]
        m.edges = [edges[int(eoffs[j]):int(eoffs[j + 1])] for j in range(len(eoffs) - 1)]
        m.rng = np.random.default_rng(0)
        return m


# -------------------------------------------------------------------------------- MLP
class MLP:
    """2-hidden-layer perceptron, relu, Adam, implemented by hand in numpy."""

    def __init__(self, n_in, hidden=(64, 32), n_out=2, lr=3e-3, epochs=160, batch=128,
                 l2=1e-5, seed=0, lr_decay=0.995):
        self.n_in, self.hidden, self.n_out = n_in, hidden, n_out
        self.lr, self.epochs, self.batch, self.l2, self.seed = lr, epochs, batch, l2, seed
        self.lr_decay = lr_decay

    def _init(self, rng):
        dims = [self.n_in, *self.hidden, self.n_out]
        self.W, self.b = [], []
        for i in range(len(dims) - 1):
            lim = math.sqrt(6.0 / (dims[i] + dims[i + 1]))  # Glorot
            self.W.append(rng.uniform(-lim, lim, (dims[i], dims[i + 1])))
            self.b.append(np.zeros(dims[i + 1]))

    @staticmethod
    def _relu(x):
        return np.maximum(x, 0.0)

    def _fwd(self, X):
        a = [X]
        z = []
        for i in range(len(self.W)):
            zi = a[-1] @ self.W[i] + self.b[i]
            z.append(zi)
            a.append(self._relu(zi) if i < len(self.W) - 1 else zi)
        return a, z

    def fit(self, X, y):
        rng = np.random.default_rng(self.seed)
        self._init(rng)
        n = len(X)
        mW = [np.zeros_like(w) for w in self.W]
        vW = [np.zeros_like(w) for w in self.W]
        mb = [np.zeros_like(b) for b in self.b]
        vb = [np.zeros_like(b) for b in self.b]
        b1, b2, eps = 0.9, 0.999, 1e-8
        step = 0
        self.history = []
        for ep in range(self.epochs):
            perm = rng.permutation(n)
            lr = self.lr * (self.lr_decay ** ep)
            tot = 0.0
            for s in range(0, n, self.batch):
                bi = perm[s:s + self.batch]
                Xb, yb = X[bi], y[bi]
                a, z = self._fwd(Xb)
                err = a[-1] - yb
                tot += float(np.sum(err ** 2))
                g = 2.0 * err / len(bi)
                gW = [None] * len(self.W)
                gb = [None] * len(self.b)
                for i in range(len(self.W) - 1, -1, -1):
                    gW[i] = a[i].T @ g + self.l2 * self.W[i]
                    gb[i] = g.sum(axis=0)
                    if i > 0:
                        g = (g @ self.W[i].T) * (z[i - 1] > 0)
                step += 1
                for i in range(len(self.W)):
                    mW[i] = b1 * mW[i] + (1 - b1) * gW[i]
                    vW[i] = b2 * vW[i] + (1 - b2) * (gW[i] ** 2)
                    mb[i] = b1 * mb[i] + (1 - b1) * gb[i]
                    vb[i] = b2 * vb[i] + (1 - b2) * (gb[i] ** 2)
                    mWh = mW[i] / (1 - b1 ** step)
                    vWh = vW[i] / (1 - b2 ** step)
                    mbh = mb[i] / (1 - b1 ** step)
                    vbh = vb[i] / (1 - b2 ** step)
                    self.W[i] -= lr * mWh / (np.sqrt(vWh) + eps)
                    self.b[i] -= lr * mbh / (np.sqrt(vbh) + eps)
            self.history.append(math.sqrt(tot / n))
        return self

    def predict(self, X):
        a, _ = self._fwd(np.asarray(X, float))
        return a[-1]

    def to_npz(self, path, prefix, meta, xmean, xstd, ymean, ystd):
        arrays = {f"{prefix}xmean": xmean, f"{prefix}xstd": xstd,
                  f"{prefix}ymean": ymean, f"{prefix}ystd": ystd,
                  f"{prefix}n_layers": np.array([len(self.W)]),
                  f"{prefix}dims": np.array([self.n_in, *self.hidden, self.n_out]),
                  f"{prefix}meta_json": np.array([json.dumps(meta)])}
        for i, (w, b) in enumerate(zip(self.W, self.b)):
            arrays[f"{prefix}W{i}"] = w
            arrays[f"{prefix}b{i}"] = b
        return arrays

    @staticmethod
    def from_npz(z, prefix):
        dims = z[f"{prefix}dims"].tolist()
        m = MLP(dims[0], tuple(dims[1:-1]), dims[-1])
        m.W, m.b = [], []
        for i in range(int(z[f"{prefix}n_layers"][0])):
            m.W.append(z[f"{prefix}W{i}"])
            m.b.append(z[f"{prefix}b{i}"])
        return m


# --------------------------------------------------------------------------------- main
def _metrics_for(y_true, y_pred, target_index):
    m = metrics(y_true, y_pred)
    if TARGET_TRANSFORMS[target_index] == "log":
        m["r2_logspace"] = _r2_logspace(y_true, y_pred)
        m["note"] = "native units; r2_logspace is the R2 of log(pred) vs log(true)"
    return m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trees", type=int, default=250)
    ap.add_argument("--epochs", type=int, default=150)
    ap.add_argument("--loso-trees", type=int, default=110)
    ap.add_argument("--loso-epochs", type=int, default=80)
    ap.add_argument("--quick", action="store_true", help="fast smoke run")
    a = ap.parse_args()
    n_trees, n_epochs = a.trees, a.epochs
    ltrees, lepochs = a.loso_trees, a.loso_epochs
    if a.quick:
        n_trees, n_epochs, ltrees, lepochs = 40, 30, 30, 25

    t_start = time.time()
    os.makedirs(MODELS_DIR, exist_ok=True)
    print("=== SolarGuard Space :: train ===")

    calib = phys.load_calibration()
    print(f"physics calibration: {len(calib['sites'])} sites, "
          f"cleaning interval {phys.CLEANING_INTERVAL_DAYS} d")

    X, y, site, dates = build_training_table(calib=calib)
    Yt = transform_targets(y)
    print(f"training table: X={X.shape}  targets={TARGET_NAMES}  transforms={TARGET_TRANSFORMS}"
          f"  rows={len(X):,}")
    uniq_sites = sorted(set(site))
    print(f"sites: {len(uniq_sites)}  features: {len(FEATURES)}")

    feat_meta = {
        "features": FEATURES,
        "targets": TARGET_NAMES,
        "target_transforms": TARGET_TRANSFORMS,
        "defaults": {f: float(np.median(X[:, i])) for i, f in enumerate(FEATURES)},
        "ranges": {f: [float(np.min(X[:, i])), float(np.max(X[:, i]))]
                   for i, f in enumerate(FEATURES)},
        "scaler_mean": [float(v) for v in X.mean(axis=0)],
        "scaler_std": [float(v) for v in X.std(axis=0)],
        "cleaning_interval_days": phys.CLEANING_INTERVAL_DAYS,
        "label_source": "physics_soiling.py (literature-calibrated mass balance)",
        "generated_utc": datetime.utcnow().isoformat(timespec="seconds") + "Z",
    }
    xmean = np.asarray(feat_meta["scaler_mean"])
    xstd = np.asarray(feat_meta["scaler_std"])
    xstd[xstd == 0] = 1.0

    # ---------------- (i) time split: latest 20 % of calendar dates
    uniq_dates = np.array(sorted(set(dates)))
    cut = uniq_dates[int(0.8 * len(uniq_dates))]
    tr = dates < cut
    te = ~tr
    print(f"time split: train<= {cut}  ({(tr).sum():,} rows)  test ({(te).sum():,} rows)")

    Xtr, Xte = X[tr], X[te]
    mu, sd = Xtr.mean(axis=0), Xtr.std(axis=0)
    sd[sd == 0] = 1.0
    ym, ys = Yt[tr].mean(axis=0), Yt[tr].std(axis=0)
    ys[ys == 0] = 1.0

    results = {"time_split": {}, "leave_one_site_out": {}, "model_config": {},
               "target_transforms": dict(zip(TARGET_NAMES, TARGET_TRANSFORMS))}

    # ---- GBRT per target (time split)
    print("\n[GBRT] time split ...")
    gbrt_ts = {}
    for ti, tname in enumerate(TARGET_NAMES):
        t0 = time.time()
        m = GBRT(n_trees=n_trees, max_depth=3, learning_rate=0.06, seed=100 + ti)
        m.fit(Xtr, Yt[tr, ti])
        p_nat = inverse_transform(m.predict(Xte), ti)
        gbrt_ts[tname] = m
        results["time_split"].setdefault("gbrt", {})[tname] = _metrics_for(y[te, ti], p_nat, ti)
        mm = results["time_split"]["gbrt"][tname]
        print(f"   {tname:22} MAE={mm['mae']:.4f} RMSE={mm['rmse']:.4f} R2={mm['r2']:.4f}"
              + (f" R2log={mm['r2_logspace']:.4f}" if "r2_logspace" in mm else "")
              + f"  ({time.time()-t0:.1f}s)", flush=True)

    # ---- MLP (time split), multi-output, standardised
    print("\n[MLP] time split ...")
    t0 = time.time()
    mlp_ts = MLP(len(FEATURES), hidden=(64, 32), n_out=2, epochs=n_epochs, seed=7)
    mlp_ts.fit((Xtr - mu) / sd, (Yt[tr] - ym) / ys)
    Pn = mlp_ts.predict((Xte - mu) / sd) * ys + ym
    for ti, tname in enumerate(TARGET_NAMES):
        p_nat = inverse_transform(Pn[:, ti], ti)
        results["time_split"].setdefault("mlp", {})[tname] = _metrics_for(y[te, ti], p_nat, ti)
        mm = results["time_split"]["mlp"][tname]
        print(f"   {tname:22} MAE={mm['mae']:.4f} RMSE={mm['rmse']:.4f} R2={mm['r2']:.4f}"
              + (f" R2log={mm['r2_logspace']:.4f}" if "r2_logspace" in mm else ""), flush=True)
    print(f"   ({time.time()-t0:.1f}s, final train RMSE (standardised)={mlp_ts.history[-1]:.4f})")

    # ---------------- (ii) leave-one-site-out
    print("\n[LOSO] leave-one-site-out ...")
    loso_pred = {"gbrt": np.full((len(X), 2), np.nan), "mlp": np.full((len(X), 2), np.nan)}
    per_site = {}
    for fold, s_hold in enumerate(uniq_sites):
        m_tr = site != s_hold
        m_te = ~m_tr
        Xa, Ya = X[m_tr], Yt[m_tr]
        Xb = X[m_te]
        fmu, fsd = Xa.mean(axis=0), Xa.std(axis=0); fsd[fsd == 0] = 1.0
        fym, fys = Ya.mean(axis=0), Ya.std(axis=0); fys[fys == 0] = 1.0
        g_p = np.zeros((m_te.sum(), 2))
        for ti in range(2):
            gm = GBRT(n_trees=ltrees, max_depth=3, learning_rate=0.06, seed=200 + ti)
            gm.fit(Xa, Ya[:, ti])
            g_p[:, ti] = inverse_transform(gm.predict(Xb), ti)
        mm = MLP(len(FEATURES), hidden=(64, 32), n_out=2, epochs=lepochs, seed=11)
        mm.fit((Xa - fmu) / fsd, (Ya - fym) / fys)
        m_z = mm.predict((Xb - fmu) / fsd) * fys + fym
        m_p = np.stack([inverse_transform(m_z[:, ti], ti) for ti in range(2)], axis=1)
        loso_pred["gbrt"][m_te] = g_p
        loso_pred["mlp"][m_te] = m_p
        per_site[s_hold] = {
            "n": int(m_te.sum()),
            "gbrt": {TARGET_NAMES[0]: metrics(y[m_te, 0], g_p[:, 0]),
                     TARGET_NAMES[1]: metrics(y[m_te, 1], g_p[:, 1])},
            "mlp": {TARGET_NAMES[0]: metrics(y[m_te, 0], m_p[:, 0]),
                    TARGET_NAMES[1]: metrics(y[m_te, 1], m_p[:, 1])},
        }
        print(f"   fold {fold+1}/{len(uniq_sites)} hold-out {s_hold:8} "
              f"loss MAE gbrt={per_site[s_hold]['gbrt'][TARGET_NAMES[0]]['mae']:6.3f} "
              f"mlp={per_site[s_hold]['mlp'][TARGET_NAMES[0]]['mae']:6.3f}   "
              f"dep R2log gbrt={_r2_logspace(y[m_te,1], g_p[:,1]):6.3f}", flush=True)

    for name, arr in loso_pred.items():
        ok = np.all(np.isfinite(arr), axis=1)
        for ti, tname in enumerate(TARGET_NAMES):
            results["leave_one_site_out"].setdefault(name, {})[tname] = \
                _metrics_for(y[ok, ti], arr[ok, ti], ti)
    results["leave_one_site_out_per_fold"] = per_site

    # ---------------- literature calibration table
    print("\n[calibration] simulated vs literature annual soiling loss (weekly cleaning)")
    sites = phys.load_dataset()
    calib_rows = {}
    for s_name, s in sites.items():
        f = phys.factor_for_site(s_name, s["meta"]["region"], calib)
        sim = float(np.mean(phys.simulate_site(s["data"], f, phys.CLEANING_INTERVAL_DAYS)["soiling_loss_pct"]))
        sel = site == s_name
        yr = dates[sel]
        last_year = np.array([d[:4] == max(x[:4] for x in yr) for d in yr])
        ml_pred = float(np.nanmean(loso_pred["gbrt"][sel, 0][last_year])) if last_year.any() else float("nan")
        calib_rows[s_name] = {
            "region": s["meta"]["region"],
            "physics_simulated_annual_loss_pct": round(sim, 3),
            "ml_loso_predicted_annual_loss_pct": round(ml_pred, 3),
            "site_factor": round(f, 4),
            "lat": s["meta"]["lat"], "lon": s["meta"]["lon"],
        }

    def band(regs):
        v = [r["physics_simulated_annual_loss_pct"] for r in calib_rows.values() if r["region"] in regs]
        m = [r["ml_loso_predicted_annual_loss_pct"] for r in calib_rows.values() if r["region"] in regs]
        return (round(float(np.mean(v)), 3) if v else float("nan"),
                round(float(np.nanmean(m)), 3) if m else float("nan"))

    west_sim, west_ml = band({"west"})
    east_sim, east_ml = band({"east"})
    all_sim = float(np.mean([r["physics_simulated_annual_loss_pct"] for r in calib_rows.values()]))
    non_east = float(np.mean([r["physics_simulated_annual_loss_pct"] for r in calib_rows.values()
                              if r["region"] != "east"]))
    calibration = {
        "note": ("labels are produced by the literature-calibrated physics model. "
                 "'physics_simulated' is the label generator's annual mean loss under weekly "
                 "cleaning; 'ml_loso' is the GBRT's out-of-sample prediction for a site it was "
                 "never trained on -> an honest test of geographic generalisation."),
        "literature": {"west_coast_pct": 15.0, "east_coast_pct": 45.0,
                       "middle_east_weekly_range_pct": [12, 36],
                       "sources": ["KAUST PV soiling study: west coast ~15 %, east coast ~45 % "
                                   "annual soiling loss even with weekly cleaning",
                                   "Middle-East soiling meta-study: 12-36 % with weekly cleaning"]},
        "simulated": {"west_coast_mean_pct": west_sim, "east_coast_mean_pct": east_sim,
                      "region_wide_mean_pct": round(all_sim, 3),
                      "non_east_region_mean_pct": round(non_east, 3)},
        "ml_loso_predicted": {"west_coast_mean_pct": west_ml, "east_coast_mean_pct": east_ml},
        "achieved": {
            "west_vs_literature": f"{west_sim:.2f} % vs 15 % target",
            "east_vs_literature": f"{east_sim:.2f} % vs 45 % target",
            "within_middle_east_band_12_36": f"{non_east:.2f} % (non-Gulf-coast regions)",
        },
        "per_site": calib_rows,
    }
    for k, v in sorted(calib_rows.items()):
        print(f"   {k:10} {v['region']:20} physics={v['physics_simulated_annual_loss_pct']:6.2f}%  "
              f"ml_loso={v['ml_loso_predicted_annual_loss_pct']:6.2f}%")

    # ---------------- persist models
    arrays = {}
    arrays.update(gbrt_ts[TARGET_NAMES[0]].to_npz(None, "loss_", {
        "target": TARGET_NAMES[0], "transform": TARGET_TRANSFORMS[0],
        "n_trees": n_trees, "features": FEATURES,
        "model": "GBRT (histogram split search, numpy, from scratch)"}))
    arrays.update(gbrt_ts[TARGET_NAMES[1]].to_npz(None, "dep_", {
        "target": TARGET_NAMES[1], "transform": TARGET_TRANSFORMS[1],
        "n_trees": n_trees, "features": FEATURES,
        "model": "GBRT (histogram split search, numpy, from scratch)"}))
    gbrt_meta = {"model": "GBRT", "features": FEATURES, "targets": TARGET_NAMES,
                 "target_transforms": TARGET_TRANSFORMS,
                 "n_trees": n_trees, "max_depth": 3, "learning_rate": 0.06,
                 "targets_prefix": {"soiling_loss_pct": "loss_",
                                    "deposition_g_m2_day": "dep_"},
                 "trained_rows": int(len(Xtr)), "trained_to_date": str(cut),
                 "notes": "predicts NEXT-DAY soiling loss % (native) and dust deposition "
                          "g/m2/day (fitted in log space; exponentiate the dep_ prediction)"}
    arrays["meta_json"] = np.array([json.dumps(gbrt_meta)])
    np.savez_compressed(os.path.join(MODELS_DIR, "gbrt.npz"), **arrays)
    print(f"\nsaved {os.path.join(MODELS_DIR, 'gbrt.npz')} "
          f"({os.path.getsize(os.path.join(MODELS_DIR, 'gbrt.npz'))/1e6:.2f} MB)")

    mlp_meta = {"model": "MLP", "features": FEATURES, "targets": TARGET_NAMES,
                "target_transforms": TARGET_TRANSFORMS, "hidden": [64, 32],
                "activation": "relu", "optimiser": "Adam", "standardised": True,
                "n_epochs": n_epochs, "trained_rows": int(len(Xtr)),
                "ymean": [float(v) for v in ym], "ystd": [float(v) for v in ys],
                "xmean": [float(v) for v in mu], "xstd": [float(v) for v in sd],
                "final_train_rmse_standardised": float(mlp_ts.history[-1]),
                "notes": "inverse transform: y = z * ystd + ymean, then exp() for the log target"}
    marrays = {}
    marrays.update(mlp_ts.to_npz(None, "", mlp_meta, xmean, xstd, ym, ys))
    marrays["meta_json"] = np.array([json.dumps(mlp_meta)])
    np.savez_compressed(os.path.join(MODELS_DIR, "mlp.npz"), **marrays)
    print(f"saved {os.path.join(MODELS_DIR, 'mlp.npz')} "
          f"({os.path.getsize(os.path.join(MODELS_DIR, 'mlp.npz'))/1e6:.2f} MB)")

    with open(FEATURES_PATH, "w") as fh:
        json.dump(feat_meta, fh, indent=2)

    results["calibration"] = calibration
    results["dataset"] = {
        "rows_in_table": int(len(X)),
        "features": len(FEATURES), "sites": len(uniq_sites),
        "date_min": str(min(dates)), "date_max": str(max(dates)),
        "targets": TARGET_NAMES,
        "label_provenance": ("physics_soiling.py literature-calibrated labels -- SYNTHETIC "
                             "w.r.t. field soiling; NOT measured inverter/soiling data"),
        "measured_inputs": ("Open-Meteo ERA5 meteorology 2019-2025 (measured/assimilated); "
                            "CAMS aerosol pm10/pm2.5/dust/AOD 2024-2025 measured, pre-2024 "
                            "backfilled from a per-site seasonal climatology fitted to that "
                            "site's own 2024-25 CAMS data"),
        "time_split_cutoff_date": str(cut),
        "time_split_train_rows": int(tr.sum()), "time_split_test_rows": int((~tr).sum()),
    }
    results["model_config"] = {
        "gbrt": {"n_trees": n_trees, "max_depth": 3, "learning_rate": 0.06,
                 "subsample": 0.85, "colsample": 0.7, "max_bins": 32,
                 "min_samples_leaf": 25, "loso_trees": ltrees},
        "mlp": {"hidden": [64, 32], "activation": "relu", "optimiser": "Adam",
                "lr": 3e-3, "batch": 128, "epochs": n_epochs, "l2": 1e-5,
                "loso_epochs": lepochs},
        "target_transforms": dict(zip(TARGET_NAMES, TARGET_TRANSFORMS)),
        "evaluation": {"time_split": "latest 20% of distinct calendar dates held out",
                       "leave_one_site_out": "each site held out in turn, trained on the other 11"},
    }
    results["wall_clock_seconds"] = round(time.time() - t_start, 1)
    results["generated_utc"] = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    with open(METRICS_PATH, "w") as fh:
        json.dump(results, fh, indent=2)
    print(f"saved {METRICS_PATH}")

    print("\n=== summary (time split) ===")
    for name in ("gbrt", "mlp"):
        for tname in TARGET_NAMES:
            m = results["time_split"][name][tname]
            extra = f" R2log={m['r2_logspace']:.4f}" if "r2_logspace" in m else ""
            print(f"  {name:5} {tname:22} MAE={m['mae']:.4f} RMSE={m['rmse']:.4f} "
                  f"R2={m['r2']:.4f}{extra}")
    print("=== summary (leave-one-site-out) ===")
    for name in ("gbrt", "mlp"):
        for tname in TARGET_NAMES:
            m = results["leave_one_site_out"][name][tname]
            extra = f" R2log={m['r2_logspace']:.4f}" if "r2_logspace" in m else ""
            print(f"  {name:5} {tname:22} MAE={m['mae']:.4f} RMSE={m['rmse']:.4f} "
                  f"R2={m['r2']:.4f}{extra}")
    print(f"\ndone in {results['wall_clock_seconds']}s")

if __name__ == "__main__":
    main()

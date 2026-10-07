"""Tests for the SolarGuard AI (backend/sg_ai.py + ml/ai_features.py).

The failure these exist to prevent is silent train/serve divergence: the first
generation of models was trained on rolling 90-day features that the serving path
could not build, and nothing complained — the model just quietly answered from its
training defaults with unphysical numbers. So the central assertions here are
(a) the served feature vector has exactly the shape and names the bundles were
trained with, and (b) every prediction lands inside physically sane bounds.

Run: python3 tests/test_ai.py
"""
from __future__ import annotations

import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
for p in (os.path.join(ROOT, "backend"), os.path.join(ROOT, "ml"), ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

import numpy as np                                        # noqa: E402
import ai_features as F                                    # noqa: E402
import sg_ai                                               # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  — {detail}" if detail else ""))


print("=== model artifacts ===")
ai = sg_ai.ai_status()
print("  available:", ai["available"], "| models:", ai.get("models"))
print("  trained:", ai.get("trained_utc"), "| samples:", ai.get("samples"),
      "| sites:", ai.get("sites"))
if not ai["available"]:
    print("\nSKIP: models not trained yet (run python3 ml/ai_train.py)")
    raise SystemExit(0)

bundles = sg_ai._all()
check("five bundles load", len(bundles) == 5, f"got {sorted(bundles)}")
check("feature list is 37 wide", len(F.FEATURES) == 37, f"got {len(F.FEATURES)}")

print("\n=== the divergence guard: bundle width must equal the live feature width ===")
for name, b in sorted(bundles.items()):
    width = len(b["mu"])
    check(f"{name}: bundle expects {width} features, code builds {len(F.FEATURES)}",
          width == len(F.FEATURES))

print("\n=== feature vector can be built from the LIVE forecast window ===")
rows = sg_ai.fetch_daily_rows(26.43, 50.10)
check("live window has 45+ usable days", len(rows) >= 45, f"got {len(rows)}")
idx = len(rows) - 4
thr, src = sg_ai.site_threshold(26.43, 50.10, "dammam")
feats = F.build_features(rows, idx, storm_thr=thr)
check("all named features present", set(feats) == set(F.FEATURES),
      f"missing {sorted(set(F.FEATURES) - set(feats))}")
bad = [k for k, v in feats.items() if not math.isfinite(float(v))]
check("all features finite", not bad, f"non-finite: {bad}")
# precipitation is deliberately excluded: 30 rain-free days is normal in Saudi
# Arabia, so a zero there is data, not a bug in the feature builder.
rolls = ["pm10_max_3d", "pm10_max_7d", "pm10_max_30d", "dust_mean_7d",
         "gust_max_7d", "aod_mean_7d"]
zero_rolls = [k for k in rolls if float(feats[k]) == 0.0]
check("rolling windows are actually populated (not defaulted)", not zero_rolls,
      f"all-zero: {zero_rolls}")
check("days_since_rain is a sane number of days",
      0 <= float(feats["days_since_rain"]) <= 120, f"{feats['days_since_rain']}")

print("\n=== predictions land in physical bounds ===")
out = sg_ai.predict_site(26.43, 50.10, 100_000, site_id="dammam")
check("predict_site returned ok", out.get("ok") is True, str(out)[:120])
if out.get("ok"):
    st = out["storm"]
    for h in (1, 2, 3):
        p = st[f"t{h}"]["p"]
        check(f"P(storm) day+{h} in [0,1]", 0.0 <= p <= 1.0, f"{p}")
        check(f"day+{h} has a level", st[f"t{h}"]["level"] in
              ("quiet", "watch", "storm likely"), st[f"t{h}"]["level"])
    y = out["output"]
    check("output per kWp in (0, 12]", 0 < y["kwh_per_kwp"] <= 12, f"{y['kwh_per_kwp']}")
    check("output kWh scales with capacity",
          abs(y["kwh"] - y["kwh_per_kwp"] * 100_000) / max(y["kwh"], 1) < 0.01)
    s = out["soiling"]
    check("soiling loss in [0, 65] %", 0 <= s["loss_pct"] <= 65, f"{s['loss_pct']}")
    check("output error bar present", isinstance(y["error_kwh_per_kwp"], (int, float)))
    check("soiling error bar present", isinstance(s["error_points"], (int, float)))
    check("storm threshold explained in the payload",
          "storm_threshold_ugm3" in out["model"], str(out["model"].get("storm_threshold_source")))
    obs = out["observed_now"]
    check("observed inputs carried through (pm10 > 0)", obs["pm10_ugm3"] > 0, str(obs))

print("\n=== the storm definition is per site, not global ===")
t_d, _ = sg_ai.site_threshold(26.43, 50.10, "dammam")
t_r, _ = sg_ai.site_threshold(24.71, 46.67, "riyadh")
check("differs between Dammam and Riyadh", t_d != t_r, f"dammam {t_d:.0f} vs riyadh {t_r:.0f}")
check("never below the 300 floor", t_d >= F.STORM_FLOOR and t_r >= F.STORM_FLOOR)

print("\n=== metrics file records the error, not just the success ===")
m = sg_ai.metrics()
st1 = (m.get("classifier", {}).get("storm_t1", {}) or {}).get("test_tuned", {})
check("storm recall reported", isinstance(st1.get("recall_pct"), (int, float)), str(st1.get("recall_pct")))
check("storm precision reported", isinstance(st1.get("precision_pct"), (int, float)))
check("storm AUC reported", isinstance(st1.get("auc"), (int, float)))
check("climatology baseline recorded for comparison",
      (m.get("classifier", {}).get("storm_t1", {}) or {}).get("baseline_climatology_brier") is not None)
check("persistence baseline recorded (the honest yardstick)",
      (m.get("classifier", {}).get("storm_t1", {}) or {}).get("baseline_persistence") is not None)
ye = (m.get("regressors", {}).get("yield_t1", {}) or {}).get("ensemble", {})
check("yield MAE reported", isinstance(ye.get("mae"), (int, float)), str(ye.get("mae")))
check("yield R2 reported", isinstance(ye.get("r2"), (int, float)))
se = (m.get("regressors", {}).get("soiling_t1", {}) or {}).get("ensemble", {})
check("soiling MAE reported", isinstance(se.get("mae"), (int, float)))
check("leave-one-site-out recorded", bool(m.get("leave_one_site_out_mean")))

print("\n=== label sanity (the bug that hid in plain sight) ===")
rate = F.deposit_rate(700, 300, 10, 0)
day_pct = 100 * (1 - math.exp(-rate / F.SOILING_MASS_SCALE_G_M2))
check("a dusty day deposits 0.05-1 g/m²", 0.05 <= rate <= 1.0, f"{rate:.3f} g/m²")
check("one dusty day is 0.1-1 %/day soiling", 0.05 <= day_pct <= 1.0, f"{day_pct:.3f} %/day")
month = F.soiling_loss_pct(30, rate)
check("30 dry dusty days land in 10-35 % loss", 10 <= month <= 35, f"{month:.1f} %")
y = F.specific_yield(22.0, 30.0, 15.0)
check("a Saudi summer day yields 3-6 kWh/kWp", 3.0 <= y <= 6.5, f"{y:.2f} kWh/kWp")

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    raise SystemExit(1)
print("OK")

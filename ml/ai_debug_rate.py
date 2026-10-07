import csv
import sys
from datetime import datetime

sys.path.insert(0, "ml")
import ai_features as F

rows = []
for r in csv.DictReader(open("data/ai/daily.csv")):
    if r["site"] != "riyadh":
        continue
    r["doy"] = float(datetime.strptime(r["date"], "%Y-%m-%d").timetuple().tm_yday)
    rows.append(r)
rows.sort(key=lambda x: x["date"])
print("site riyadh, rows:", len(rows))
print("\nsample computed rates (should be ~0.05-0.5 g/m2/day):")
print(f"  {'date':<12} {'pm10max':>8} {'dustmax':>8} {'gust':>6} {'rain':>6} -> {'rate':>8} {'day%':>7}")
for r in rows[100:112]:
    pm, dm, gs, pr = (F._f(r["pm10_max"]), F._f(r["dust_max"]),
                      F._f(r["gust_max_ms"]), F._f(r["precip_mm"]))
    rate = F.deposit_rate(pm, dm, gs, pr)
    day = 100 * (1 - __import__("math").exp(-rate / F.SOILING_MASS_SCALE_G_M2))
    print(f"  {r['date']:<12} {pm:>8.1f} {dm:>8.1f} {gs:>6.1f} {pr:>6.1f} -> {rate:>8.4f} {day:>7.3f}")

rates = [F.deposit_rate(F._f(r["pm10_max"]), F._f(r["dust_max"]),
                        F._f(r["gust_max_ms"]), F._f(r["precip_mm"])) for r in rows]
s = sorted(rates)
q = lambda p: s[int(len(s) * p / 100)]
print(f"\nriyadh rate percentiles: p10 {q(10):.4f} p50 {q(50):.4f} p90 {q(90):.4f} p99 {q(99):.4f} max {s[-1]:.3f}")
print("rain days (>1mm):", sum(1 for r in rows if F._f(r["precip_mm"]) > 1))
print("days with dust_max == 0:", sum(1 for r in rows if F._f(r["dust_max"]) == 0))
print("days with pm10_max == 0:", sum(1 for r in rows if F._f(r["pm10_max"]) == 0))

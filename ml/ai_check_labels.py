
import sys, statistics
sys.path.insert(0, "ml")
import ai_features as F
import csv, collections

rows_by = collections.defaultdict(list)
from datetime import datetime
for r in csv.DictReader(open("data/ai/daily.csv")):
    r["doy"] = float(datetime.strptime(r["date"], "%Y-%m-%d").timetuple().tm_yday)
    rows_by[r["site"]].append(r)
for s in rows_by: rows_by[s].sort(key=lambda x: x["date"])

soiling, yields, rates, day_rates = [], [], [], []
for site, rows in rows_by.items():
    for i in range(45, len(rows) - 1, 7):
        s = F.label_soiling(rows, i + 1)
        soiling.append(s)
        yields.append(F.label_yield(rows[i + 1], s))
        rates.append(F.deposit_rate(F._f(rows[i]["pm10_max"]), F._f(rows[i]["dust_max"]),
                                    F._f(rows[i]["gust_max_ms"]), F._f(rows[i]["precip_mm"])))
        # what a rate of this size means per day
        day_rates.append(100 * (1 - __import__("math").exp(-rates[-1] / F.SOILING_MASS_SCALE_G_M2)))
def q(v, p): return sorted(v)[int(len(v) * p / 100)]
print(f"deposition  g/m2/day : p50 {q(rates,.5):.3f}  p90 {q(rates,.9):.3f}  p99 {q(rates,.99):.3f}")
print(f"soiling loss %       : mean {statistics.mean(soiling):.1f}  p50 {q(soiling,.5):.1f}  "
      f"p90 {q(soiling,.9):.1f}  p99 {q(soiling,.99):.1f}  max {max(soiling):.1f}")
print(f"yield kWh/kWp/day    : mean {statistics.mean(yields):.2f}  p10 {q(yields,.1):.2f}  "
      f"p50 {q(yields,.5):.2f}  p90 {q(yields,.9):.2f}")
print("  (Saudi reality: 4.5-7.0 kWh/kWp/day in summer, 2.5-4.5 in winter)")
print(f"single-day soiling %/day: p50 {q(day_rates,.5):.3f} p90 {q(day_rates,.9):.3f} p99 {q(day_rates,.99):.3f}  (published 0.2-0.8)")
print(f"implied daily soiling rate %/day: {statistics.mean(rates)*100/F.SOILING_MASS_SCALE_G_M2*100/100:.3f} "
      f"-> over 30 dry days {100*(1-__import__('math').exp(-30*statistics.mean(rates)/F.SOILING_MASS_SCALE_G_M2)):.1f}%")

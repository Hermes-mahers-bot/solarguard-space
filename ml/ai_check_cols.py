import collections
import csv
import statistics

rows = list(csv.DictReader(open("data/ai/daily.csv")))


def stats(col, by=None):
    vals = [float(r[col]) for r in rows if r.get(col) not in (None, "", "None")]
    vals.sort()
    q = lambda p: vals[int(len(vals) * p / 100)]
    print(f"  {col:16} n={len(vals):>6} min {vals[0]:>9.2f} p10 {q(10):>8.2f} p50 {q(50):>8.2f} "
          f"p90 {q(90):>8.2f} p99 {q(99):>8.2f} max {vals[-1]:>9.2f}")


print("harvested column distributions (all 12 sites):")
for c in ("ghi_mj_m2", "tmean_c", "gust_max_ms", "pm10_max", "pm10_mean",
          "dust_max", "dust_mean", "aod_mean", "precip_mm", "rh_mean_pct"):
    stats(c)

print("\nper-site GHI mean / PM10 max mean / dust max mean:")
by = collections.defaultdict(list)
for r in rows:
    by[r["site"]].append(r)
print(f"  {'site':<9} {'GHI MJ/m2':>10} {'=kWh/m2':>8} {'PM10max':>9} {'dustmax':>8} {'rain d>1mm':>11}")
for s in sorted(by):
    v = by[s]
    ghi = statistics.mean(float(x["ghi_mj_m2"]) for x in v)
    pm = statistics.mean(float(x["pm10_max"]) for x in v)
    dm = statistics.mean(float(x["dust_max"]) for x in v)
    rain = sum(1 for x in v if float(x["precip_mm"]) > 1.0)
    print(f"  {s:<9} {ghi:>10.2f} {ghi/3.6:>8.2f} {pm:>9.1f} {dm:>8.1f} {rain:>11}")

print("\nsanity: Saudi daily GHI summer is 20-28 MJ/m2, winter 10-16 MJ/m2")
print("        so 22 MJ/m2 = 6.1 kWh/m2 -> about 5 kWh/kWp at PR 0.8")

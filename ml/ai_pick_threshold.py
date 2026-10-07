import collections
import csv

rows = list(csv.DictReader(open("data/ai/daily.csv")))
vals = sorted(float(r["pm10_max"]) for r in rows if r["pm10_max"] not in (None, "", "None"))


def pct(p):
    return vals[int(len(vals) * p / 100)]


print("PM10 daily max percentiles (all sites, all days):")
for p in (50, 75, 90, 95, 97, 98, 99, 99.5, 99.9):
    print(f"  p{p:<5} {pct(p):>8.1f} µg/m³")
print(f"  max   {vals[-1]:>8.1f}")

print("\nevent rate at candidate thresholds:")
for t in (200, 300, 400, 500, 700, 1000):
    n = sum(1 for v in vals if v >= t)
    print(f"  pm10_max >= {t:>4}: {n:>5} days ({100*n/len(vals):5.2f}%)")

print("\nper-site share of days above 500 µg/m³:")
by = collections.defaultdict(lambda: [0, 0])
for r in rows:
    v = r["pm10_max"]
    if v in (None, "", "None"):
        continue
    by[r["site"]][0] += 1
    if float(v) >= 500:
        by[r["site"]][1] += 1
for s, (n, k) in sorted(by.items()):
    print(f"  {s:<8} {k:>5}/{n:<5} = {100*k/n:5.2f}%")

print("\nper-site days above 1000 µg/m³ (LOSO folds need positives):")
by2 = collections.defaultdict(lambda: [0, 0])
for r in rows:
    v = r["pm10_max"]
    if v in (None, "", "None"):
        continue
    by2[r["site"]][0] += 1
    if float(v) >= 1000:
        by2[r["site"]][1] += 1
for s, (n, k) in sorted(by2.items()):
    print(f"  {s:<8} {k:>5}/{n:<5} = {100*k/n:5.2f}%")

print("\nmonthly distribution of >=500 days (does it look like storm season?):")
mon = collections.Counter()
for r in rows:
    v = r["pm10_max"]
    if v not in (None, "", "None") and float(v) >= 500:
        mon[r["date"][5:7]] += 1
for m in sorted(mon):
    print(f"  {m}: {'#' * max(1, mon[m] // 8)} {mon[m]}")

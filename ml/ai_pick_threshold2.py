"""Pick the storm definition: absolute vs per-site relative."""
import collections
import csv
import statistics

rows = list(csv.DictReader(open("data/ai/daily.csv")))
by = collections.defaultdict(list)
for r in rows:
    v = r["pm10_max"]
    if v not in (None, "", "None"):
        by[r["site"]].append(float(v))

print("site                 median   p90    p99    thr=3xmedian(min300)   days>=thr   rate")
tot_days = tot_ev = 0
rates = []
for s in sorted(by):
    v = sorted(by[s])
    med = statistics.median(v)
    p90 = v[int(len(v) * 0.90)]
    p99 = v[int(len(v) * 0.99)]
    thr = max(3.0 * med, 300.0)
    ev = sum(1 for x in v if x >= thr)
    tot_days += len(v)
    tot_ev += ev
    rates.append(100 * ev / len(v))
    print(f"{s:<12} {med:>8.1f} {p90:>7.0f} {p99:>7.0f}   {thr:>10.0f}          {ev:>5}   {100*ev/len(v):5.2f}%")

print(f"\noverall: {tot_ev}/{tot_days} = {100*tot_ev/tot_days:.2f}%")
print(f"per-site rate: min {min(rates):.1f}% max {max(rates):.1f}% "
      f"(a BALANCED target; compare 1000 ug/m3 where 7/12 sites had zero events)")
print(f"sites with zero events: {sum(1 for r in rates if r == 0)}")

print("\nmonthly shape (should peak in the shamal season, Feb-May):")
mon = collections.Counter()
for r in rows:
    v = r["pm10_max"]
    if v in (None, "", "None"):
        continue
    s = r["site"]
    med = statistics.median(by[s])
    if float(v) >= max(3.0 * med, 300.0):
        mon[r["date"][5:7]] += 1
for m in sorted(mon):
    print(f"  {m}: {'#' * max(1, mon[m] // 6)} {mon[m]}")

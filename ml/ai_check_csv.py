import collections
import csv
import os

p = "data/ai/daily.csv"
if not os.path.exists(p):
    print("not ready yet")
    raise SystemExit

rows = list(csv.DictReader(open(p)))
by = collections.Counter(r["site"] for r in rows)
print("rows:", len(rows), "| sites:", len(by))
print("per site:", dict(by))
print("columns:", len(rows[0]))
print("sample:", {k: rows[0][k] for k in list(rows[0])[:14]})


def nn(c):
    return sum(1 for x in rows if x.get(c) not in (None, "", "None"))


for c in ("pm10_max", "dust_max", "aod_mean", "ghi_mj_m2", "gust_max_ms",
          "rh_mean_pct", "pm10_mean", "wind_dir_deg"):
    print(f"  {c:14} non-null {nn(c):>6}/{len(rows)}")

storms = [x for x in rows if x.get("pm10_max") and float(x["pm10_max"]) >= 200]
print(f"storm days (pm10_max>=200): {len(storms)} ({100*len(storms)/len(rows):.1f}%)")
per_site = collections.Counter(x["site"] for x in storms)
print("storm days per site:", dict(per_site))
print("date range:", min(x["date"] for x in rows), "..", max(x["date"] for x in rows))

need = ("pm10_max", "dust_max", "aod_mean", "ghi_mj_m2", "gust_max_ms", "tmean_c")
ok = [r for r in rows if all(r.get(c) not in (None, "", "None") for c in need)]
print("complete rows (all key columns):", len(ok), "/", len(rows))

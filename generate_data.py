"""Generate a synthetic retail dataset for the portfolio demo.

Everything here is invented: the company, branches, products and numbers.
It mimics the shape of a multi-branch retail chain (POS branches plus an
online store) so the same KPIs can be shown: sales vs last year,
like-for-like, target achievement, margin and returns.

Outputs:
  data/branches.csv, data/products.csv, data/sales.csv, data/targets.csv
  dashboard-data.json, the monthly aggregate for the web dashboard (into the website folder when it sits
  next to this one, otherwise into data/)
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

rng = np.random.default_rng(2026)
HERE = Path(__file__).parent
DATA = HERE / "data"
SITE = HERE.parent / "mohamed-elsonbaty.github.io"
DATA.mkdir(exist_ok=True)

START, END = pd.Timestamp("2024-01-01"), pd.Timestamp("2026-09-30")
dates = pd.date_range(START, END, freq="D")

# ---------------------------------------------------------------- branches
AREAS = {
    "Jeddah": ["Al Rawdah", "Al Salamah", "Obhur", "Al Hamra", "Al Safa", "Al Naeem", "Al Marwah"],
    "Riyadh": ["Al Olaya", "Al Malqa", "Al Nakheel", "Al Yasmin", "Al Sahafa", "Al Rabwah"],
    "Makkah": ["Al Aziziyah", "Al Awali", "Al Shawqiyah", "Al Zahir"],
    "Madinah": ["Quba", "Al Aziziyah M", "Al Uyun"],
    "Eastern": ["Dammam Corniche", "Al Khobar North", "Dhahran", "Al Jubail"],
    "Taif": ["Al Hawiyah", "Shihar"],
}
rows, bid = [], 101
for area, districts in AREAS.items():
    for d in districts:
        opened = pd.Timestamp("2021-01-01")
        if rng.random() < 0.18:  # a few branches open during the period
            opened = pd.Timestamp(rng.choice(pd.date_range("2024-06-01", "2026-03-01", freq="MS")))
        rows.append(dict(branch_id=bid, branch_name=f"{bid}-{d}", area=area, channel="POS",
                         open_date=opened.date(), size=round(float(rng.lognormal(0, 0.35)), 2)))
        bid += 1
rows.append(dict(branch_id=900, branch_name="900-Online Store", area="Online", channel="Online",
                 open_date=pd.Timestamp("2021-01-01").date(), size=1.6))
branches = pd.DataFrame(rows)

# ---------------------------------------------------------------- products
CATS = {
    # category: (price range SAR, margin range, popularity weight, name parts)
    "Perfumes": ((140, 620), (0.45, 0.62), 1.0, ["Amber Night", "White Musk", "Royal Oud", "Desert Rose", "Saffron Mist", "Velvet Leather", "Citrus Bloom", "Midnight Iris"]),
    "Oud & Incense": ((60, 950), (0.50, 0.68), 0.8, ["Cambodi Oud", "Muattar", "Bakhoor Classic", "Oud Chips", "Mabthoth", "Oud Oil", "Incense Sticks"]),
    "Skincare": ((35, 210), (0.40, 0.55), 0.9, ["Rose Cream", "Argan Oil", "Musk Lotion", "Body Mist", "Hand Cream", "Hair Oil"]),
    "Honey": ((55, 320), (0.30, 0.45), 0.6, ["Sidr Honey", "Samar Honey", "Acacia Honey", "Mountain Honey", "Royal Jelly"]),
    "Nuts & Dates": ((18, 140), (0.22, 0.38), 1.2, ["Ajwa Dates", "Sukkari Dates", "Mixed Nuts", "Pistachio", "Cashew", "Almond"]),
    "Gift Sets": ((120, 540), (0.42, 0.58), 0.5, ["Eid Box", "Signature Set", "Discovery Kit", "Luxury Box"]),
}
prows, pid = [], 10001
for cat, (pr, mr, pop, names) in CATS.items():
    for n in names:
        for size in ("", " Large") if rng.random() < 0.6 else ("",):
            price = round(float(rng.uniform(*pr)) * (1.6 if size else 1), 0)
            margin = float(rng.uniform(*mr))
            prows.append(dict(product_id=pid, product_name=f"{n}{size}", category=cat,
                              unit_price=price, unit_cost=round(price * (1 - margin), 2),
                              popularity=round(pop * float(rng.lognormal(0, 0.6)), 3)))
            pid += 1
products = pd.DataFrame(prows)

# ---------------------------------------------------------------- seasonality
RAMADAN = [("2024-03-11", "2024-04-09"), ("2025-03-01", "2025-03-30"), ("2026-02-18", "2026-03-19")]
EID_ADHA = ["2024-06-16", "2025-06-06", "2026-05-27"]
season = np.ones(len(dates))
for s, e in RAMADAN:
    m = (dates >= s) & (dates <= e)
    season[m] *= np.linspace(1.3, 2.4, m.sum())          # builds towards Eid
    eid = (dates > e) & (dates <= pd.Timestamp(e) + pd.Timedelta(days=3))
    season[eid] *= 1.8
for d in EID_ADHA:
    m = (dates >= pd.Timestamp(d) - pd.Timedelta(days=6)) & (dates <= d)
    season[m] *= 1.6
for y in (2024, 2025, 2026):  # National Day 23 Sep
    m = (dates >= f"{y}-09-20") & (dates <= f"{y}-09-24")
    season[m] *= 1.35
weekday = np.array([1.0, 0.95, 0.95, 1.05, 1.25, 1.15, 1.35])[dates.dayofweek]  # Mon..Sun, weekend Thu-Sat busier
t = (dates - START).days.values / 365
growth = np.where(dates < "2026-01-01", 1 + 0.07 * t, (1 + 0.07 * 2) * 0.93)  # 2026 softer market

# category mix shifts by season (gift sets and oud peak in Ramadan)
cat_season = {c: np.ones(len(dates)) for c in CATS}
for s, e in RAMADAN:
    m = (dates >= s) & (dates <= pd.Timestamp(e) + pd.Timedelta(days=3))
    cat_season["Gift Sets"][m] *= 2.2
    cat_season["Oud & Incense"][m] *= 1.5
    cat_season["Nuts & Dates"][m] *= 1.7

# ---------------------------------------------------------------- sales lines
frames = []
for b in branches.itertuples():
    open_mask = dates >= pd.Timestamp(b.open_date)
    # new branches ramp up over ~4 months
    ramp = np.clip((dates - pd.Timestamp(b.open_date)).days.values / 120, 0.35, 1.0)
    # each branch has its own trend so some beat target and some miss
    btrend = 1 + rng.normal(0, 0.12) * t
    online_boost = np.where(b.channel == "Online", 1 + 0.25 * t, 1.0)
    base = 0.55 * b.size * season * weekday * growth * ramp * btrend * online_boost * open_mask
    for p in products.itertuples():
        lam = base * p.popularity * cat_season[p.category] * (160 / (p.unit_price + 40))
        qty = rng.poisson(lam)
        idx = np.nonzero(qty)[0]
        if not len(idx):
            continue
        q = qty[idx]
        disc = rng.choice([0, 0, 0, 0.05, 0.10, 0.15], size=len(idx))
        frames.append(pd.DataFrame({
            "date": dates[idx], "branch_id": b.branch_id, "product_id": p.product_id,
            "qty": q, "net_sales": np.round(q * p.unit_price * (1 - disc), 2),
            "cost": np.round(q * p.unit_cost, 2), "is_refund": False,
        }))
sales = pd.concat(frames, ignore_index=True)

# returns: ~2.5% of lines come back 1-20 days later (online returns more)
ret_rate = np.where(sales.branch_id == 900, 0.06, 0.02)
r = sales[rng.random(len(sales)) < ret_rate].copy()
r["date"] = r["date"] + pd.to_timedelta(rng.integers(1, 21, len(r)), unit="D")
r = r[r["date"] <= END]
rq = np.minimum(r["qty"].values, rng.integers(1, 3, len(r)))
share = rq / r["qty"].values
r["qty"] = -rq
r["net_sales"] = -np.round(r["net_sales"].values * share, 2)
r["cost"] = -np.round(r["cost"].values * share, 2)
r["is_refund"] = True
sales = pd.concat([sales, r], ignore_index=True).sort_values(["date", "branch_id", "product_id"])
sales["channel"] = np.where(sales.branch_id == 900, "Online", "POS")

# ---------------------------------------------------------------- targets
sales["month"] = sales["date"].dt.to_period("M")
mb = sales.groupby(["branch_id", "month"])["net_sales"].sum()
trows = []
for b in branches.itertuples():
    for m in pd.period_range("2025-01", "2026-12", freq="M"):
        ly = mb.get((b.branch_id, m - 12), np.nan)
        if not np.isnan(ly) and ly > 0 and m - 12 >= pd.Period(b.open_date, "M") + 4:
            tgt = ly * 1.10                                # plan: +10% on last year
        else:                                              # new branch: recent average run-rate
            recent = [mb.get((b.branch_id, m - k), np.nan) for k in range(1, 4)]
            recent = [x for x in recent if not np.isnan(x)]
            if not recent:
                continue
            tgt = np.mean(recent) * 1.05
        trows.append(dict(month=m.to_timestamp().date(), branch_id=b.branch_id, target=round(float(tgt), -2)))
targets = pd.DataFrame(trows)

# ---------------------------------------------------------------- write CSVs
branches.drop(columns="size").to_csv(DATA / "branches.csv", index=False)
products.drop(columns="popularity").to_csv(DATA / "products.csv", index=False)
sales.drop(columns="month").assign(date=lambda d: d["date"].dt.date).to_csv(DATA / "sales.csv", index=False)
targets.to_csv(DATA / "targets.csv", index=False)

# ---------------------------------------------------------------- web aggregate
s = sales.merge(products[["product_id", "category"]], on="product_id")
s["m"] = s["date"].dt.strftime("%Y-%m")
g = s.groupby(["m", "branch_id", "category", "is_refund"]).agg(v=("net_sales", "sum"), c=("cost", "sum"), q=("qty", "sum")).reset_index()
months = sorted(g["m"].unique())
cats = list(CATS)
fact = []
for row in g.itertuples():
    fact.append([months.index(row.m), int(row.branch_id), cats.index(row.category), int(row.is_refund),
                 round(row.v), round(row.c), int(row.q)])
out = {
    "note": "Synthetic data. Every name and number is invented.",
    "months": months, "categories": cats,
    "branches": [dict(id=int(b.branch_id), name=b.branch_name, area=b.area, channel=b.channel,
                      open=str(b.open_date)) for b in branches.itertuples()],
    "fields": ["month", "branch", "category", "refund", "sales", "cost", "qty"],
    "fact": fact,
    "targets": [[t.month.strftime("%Y-%m"), int(t.branch_id), int(t.target)] for t in targets.itertuples()
                if t.month.strftime("%Y-%m") in months],
}
JSON_OUT = SITE / "dashboard-data.json" if SITE.exists() else DATA / "dashboard-data.json"
JSON_OUT.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")

print(f"branches {len(branches)}  products {len(products)}  sales rows {len(sales):,}  "
      f"refund rows {int(sales.is_refund.sum()):,}  targets {len(targets)}")
print("net sales by year:", sales.groupby(sales.date.dt.year).net_sales.sum().round(-3).to_dict())
print("json KB:", round(JSON_OUT.stat().st_size / 1024), "->", JSON_OUT)

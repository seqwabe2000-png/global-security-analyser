"""
Builds data/jse_universe.csv by merging the scraped rank/market-cap list with
the hand-curated GICS sector/industry map, computing a JSE-calibrated
market-cap tier for each stock, and deriving the Yahoo Finance (.JO) ticker.

Run once (or whenever data/jse_universe_raw.csv / jse_sector_map.csv change):
    python3 scripts/build_universe.py
"""
import csv
import os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_PATH = os.path.join(BASE, "data", "jse_universe_raw.csv")
SECTOR_PATH = os.path.join(BASE, "data", "jse_sector_map.csv")
OUT_PATH = os.path.join(BASE, "data", "jse_universe.csv")

# JSE-calibrated market cap tiers (ZAR). These are NOT the same absolute
# thresholds used for the US market -- they're chosen so the ~259-stock JSE
# universe splits into meaningfully-sized buckets. Edit freely.
TIERS = [
    ("Mega Cap", 200_000_000_000, float("inf")),
    ("Large Cap", 50_000_000_000, 200_000_000_000),
    ("Mid Cap", 10_000_000_000, 50_000_000_000),
    ("Small Cap", 2_000_000_000, 10_000_000_000),
    ("Micro Cap", 0, 2_000_000_000),
]


def parse_market_cap(s):
    s = s.strip()
    if not s or s == "-":
        return None
    mult = 1
    if s.endswith("T"):
        mult = 1_000_000_000_000
        s = s[:-1]
    elif s.endswith("B"):
        mult = 1_000_000_000
        s = s[:-1]
    elif s.endswith("M"):
        mult = 1_000_000
        s = s[:-1]
    try:
        return float(s) * mult
    except ValueError:
        return None


def tier_for(market_cap):
    if market_cap is None:
        return "Unknown"
    for name, lo, hi in TIERS:
        if lo <= market_cap < hi:
            return name
    return "Unknown"


def main():
    with open(SECTOR_PATH, newline="", encoding="utf-8") as f:
        sector_rows = {r["symbol"]: r for r in csv.DictReader(f)}

    with open(RAW_PATH, newline="", encoding="utf-8") as f:
        raw_rows = list(csv.DictReader(f))

    out_rows = []
    missing_sector = []
    for r in raw_rows:
        sym = r["symbol"]
        mc = parse_market_cap(r["market_cap_display"])
        sec = sector_rows.get(sym)
        if sec is None:
            missing_sector.append(sym)
            gics_sector, industry = "Unknown", "Unknown"
        else:
            gics_sector, industry = sec["gics_sector"], sec["industry"]
        out_rows.append(
            {
                "rank": r["rank"],
                "symbol": sym,
                "yf_ticker": f"{sym}.JO",
                "name": r["name"],
                "market_cap_zar": int(mc) if mc is not None else "",
                "market_cap_tier": tier_for(mc),
                "gics_sector": gics_sector,
                "industry": industry,
            }
        )

    with open(OUT_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "rank",
                "symbol",
                "yf_ticker",
                "name",
                "market_cap_zar",
                "market_cap_tier",
                "gics_sector",
                "industry",
            ],
        )
        writer.writeheader()
        writer.writerows(out_rows)

    print(f"Wrote {len(out_rows)} rows to {OUT_PATH}")
    if missing_sector:
        print(f"WARNING: {len(missing_sector)} symbols missing from sector map: {missing_sector}")

    # tier distribution summary
    from collections import Counter
    dist = Counter(r["market_cap_tier"] for r in out_rows)
    for tier_name, *_ in TIERS:
        print(f"  {tier_name}: {dist.get(tier_name, 0)}")
    print(f"  Unknown: {dist.get('Unknown', 0)}")


if __name__ == "__main__":
    main()

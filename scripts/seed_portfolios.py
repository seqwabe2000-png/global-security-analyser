"""
Seed data/portfolios/ with the Easy Equities portfolio from 27-Aug-2026 (as pasted
from Easy_Equities_Portfolio_Weights.xlsx), a TFSA model and an Ideas watchlist.
Safe to re-run (overwrites the seeded files only).  Run: python3 scripts/seed_portfolios.py
"""
import os
import sys

import pandas as pd

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
from src import portfolio as pf  # noqa: E402

inst = pd.read_csv(os.path.join(BASE, "data", "universe", "instruments.csv"))
paste = open(os.path.join(BASE, "data", "seed", "ee_portfolio_2026_08_27.tsv")).read()
p = pf.parse_paste(paste)
h = pf.build_holdings(p, p.mapping, inst)
pf.save_portfolio("live", "EE_Portfolio_2026-08-27", h,
                  "Easy Equities (ZAR, USD, TFSA, Crypto accounts + cash) from EEP_2026_08_27. "
                  "SB Brent Crude ETN and FNB MidCap ETF need a Yahoo ticker -- add them in the Builder.",
                  {"value_ccy": "ZAR"})
print(f"live: {len(h)} holdings, {int((h.ticker == '').sum())} without ticker")

tfsa = pd.DataFrame({
    "ticker": ["STXNDQ.JO", "STX500.JO", "STX40.JO", "STXEMG.JO", "STXRES.JO", "SYGEU.JO", "SYGP.JO", "CASH"],
    "weight": [0.25, 0.25, 0.12, 0.10, 0.10, 0.06, 0.07, 0.05]})
tfsa["name"] = [pf.lookup_name(t, inst) for t in tfsa["ticker"]]
tfsa["account"] = "EE_TSFA_Acc"
pf.save_portfolio("model", "TFSA_Balanced_Model", pf.normalise_holdings(tfsa),
                  "Example model: TFSA ETF mix with 5% cash")

ideas = ["MP", "ONDS", "POET", "SNPS", "WDC", "GDX", "AFT.JO", "LAB.JO", "RBX.JO", "RLO.JO", "SYGEMF.JO", "TAN"]
wl = pd.DataFrame({"ticker": ideas, "name": [pf.lookup_name(t, inst) for t in ideas], "category": "Idea"})
pf.save_portfolio("watchlist", "Ideas", pf.normalise_holdings(wl), "Names from the older weights sheet not currently held")
print("seeded model + watchlist")

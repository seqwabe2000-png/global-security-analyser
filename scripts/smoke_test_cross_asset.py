"""
Extra smoke test: exercises a few pages with the universe picker switched
to non-default Asset Class / Market combinations (Crypto, US equities,
Commodity, Currency, Bond/Rate) to catch bugs that only show up off the
South-Africa-equity default path (e.g. NaN market caps, missing 'industry'
assumptions). Uses the same mocked data approach as smoke_test_pages.py.

Run: python3 scripts/smoke_test_cross_asset.py
"""
import os
import sys
from datetime import datetime, timedelta
from unittest import mock

import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from streamlit.testing.v1 import AppTest  # noqa: E402

_CACHE = {}


def _fake_ohlcv(n=900, seed=1, start_price=100.0):
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(end=datetime.now(), periods=n)
    rets = rng.normal(0.0003, 0.018, n)
    close = start_price * np.cumprod(1 + rets)
    high = close * (1 + np.abs(rng.normal(0, 0.006, n)))
    low = close * (1 - np.abs(rng.normal(0, 0.006, n)))
    open_ = close * (1 + rng.normal(0, 0.004, n))
    vol = rng.integers(1_000, 5_000_000, n).astype(float)
    return pd.DataFrame(
        {"Open": open_, "High": high, "Low": low, "Close": close, "Adj Close": close, "Volume": vol},
        index=dates,
    )


def fake_get_history(ticker, period="5y", interval="1d", force_refresh=False):
    if ticker not in _CACHE:
        _CACHE[ticker] = _fake_ohlcv(seed=abs(hash(ticker)) % (2**32))
    return _CACHE[ticker]


def fake_get_history_bulk(tickers, period="1y", interval="1d", force_refresh=False, progress_cb=None):
    return {t: fake_get_history(t) for t in tickers}


CASES = [
    ("pages/03_Screener.py", {"screener_ac": ["Crypto"]}),
    ("pages/03_Screener.py", {"screener_ac": ["Equity"], "screener_mkt": ["United States"]}),
    ("pages/03_Screener.py", {"screener_ac": ["Mutual Fund"]}),
    ("pages/04_Charts.py", {"charts_ac": ["Crypto"]}),
    ("pages/04_Charts.py", {"charts_ac": ["Mutual Fund"]}),
    ("pages/04_Charts.py", {"charts_ac": ["Commodity"]}),
    ("pages/04_Charts.py", {"charts_ac": ["Currency"]}),
    ("pages/04_Charts.py", {"charts_ac": ["Bond/Rate"]}),
    ("pages/05_Market_Breadth.py", {"breadth_ac": ["Equity"], "breadth_mkt": ["United States"]}),
    ("pages/14_Rolling_Stats_Beta.py", {"rsb_ac": ["Crypto"]}),
    ("pages/14_Rolling_Stats_Beta.py", {"rsb_ac": ["Bond/Rate"]}),
    ("pages/14_Rolling_Stats_Beta.py", {"rsb_ac": ["Mutual Fund"]}),
    ("pages/15_Relative_Performance.py", {"rp_ac": ["Equity"], "rp_mkt": ["United States"]}),
    ("pages/16_Pairs_Trade.py", {"pairs_ac": ["Crypto"]}),
    ("pages/12_News.py", {"news_ac": ["Crypto"]}),
    ("pages/09_Mutual_Funds.py", {}),
]

results = []
with mock.patch("src.data.get_history", side_effect=fake_get_history), \
     mock.patch("src.data.get_history_bulk", side_effect=fake_get_history_bulk):
    for rel_path, widget_values in CASES:
        page_path = os.path.join(BASE, rel_path)
        label = f"{rel_path}  {widget_values}"
        try:
            at = AppTest.from_file(page_path, default_timeout=30)
            at.session_state["authenticated"] = True
            at.session_state["username"] = "smoketest"
            at.run()
            for key, values in widget_values.items():
                for ms in at.multiselect:
                    if ms.key == key:
                        ms.set_value(values)
            at.run()
            if at.exception:
                results.append((label, "FAIL", str(at.exception[0])))
            else:
                results.append((label, "OK", ""))
        except Exception as e:
            results.append((label, "ERROR", f"{type(e).__name__}: {e}"))

print(f"\n{'CASE':75s} {'STATUS':8s} DETAIL")
print("-" * 130)
n_fail = 0
for label, status, detail in results:
    if status != "OK":
        n_fail += 1
    print(f"{label:75s} {status:8s} {detail[:400]}")
print("-" * 130)
print(f"{len(results) - n_fail}/{len(results)} cross-asset cases ran cleanly.")
sys.exit(1 if n_fail else 0)

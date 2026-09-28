"""
Offline smoke test: runs every page through Streamlit's AppTest harness with
synthetic (mocked) price/news/SENS data standing in for Yahoo Finance /
Sharenet / Google News -- this sandbox has no route to any of those (see
README), so this is the same "mocked-data" verification approach the
original JSE-only build used, extended to the new global-universe pages.

This does NOT verify that live Yahoo Finance tickers actually resolve
correctly (run `python3 scripts/test_data_connection.py` on a machine with
internet access for that) -- it verifies that every page's Streamlit
logic runs top-to-bottom without crashing, against realistic-shaped data.

Run: python3 scripts/smoke_test_pages.py
"""
import os
import sys
import traceback
from datetime import datetime, timedelta
from unittest import mock

import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from streamlit.testing.v1 import AppTest  # noqa: E402


def _fake_ohlcv(n=900, seed=1, start_price=100.0):
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(end=datetime.now(), periods=n)
    rets = rng.normal(0.0003, 0.018, n)
    close = start_price * np.cumprod(1 + rets)
    high = close * (1 + np.abs(rng.normal(0, 0.006, n)))
    low = close * (1 - np.abs(rng.normal(0, 0.006, n)))
    open_ = close * (1 + rng.normal(0, 0.004, n))
    vol = rng.integers(1_000, 5_000_000, n).astype(float)
    df = pd.DataFrame(
        {"Open": open_, "High": high, "Low": low, "Close": close, "Adj Close": close, "Volume": vol},
        index=dates,
    )
    return df


_CACHE = {}


def fake_get_history(ticker, period="5y", interval="1d", force_refresh=False):
    if ticker not in _CACHE:
        _CACHE[ticker] = _fake_ohlcv(seed=abs(hash(ticker)) % (2**32))
    return _CACHE[ticker]


def fake_get_history_bulk(tickers, period="1y", interval="1d", force_refresh=False, progress_cb=None):
    return {t: fake_get_history(t) for t in tickers}


def fake_fetch_sens(symbol=None, days=60, max_rows=200):
    now = datetime.now()
    rows = [
        {"datetime": now - timedelta(days=i * 5), "code": symbol or "TST", "headline": f"Fake announcement {i}",
         "url": "https://example.com", "price": 100 + i, "move": 1.0, "pct_move": 1.0}
        for i in range(3)
    ]
    return pd.DataFrame(rows)


def fake_fetch_news(query, days=30, max_items=25):
    now = datetime.now()
    rows = [
        {"published": now - timedelta(days=i), "title": f"Fake news {i} about {query[:20]}", "source": "Test Wire",
         "link": "https://example.com"}
        for i in range(3)
    ]
    return pd.DataFrame(rows)


PAGES = sorted(
    os.path.join(BASE, "pages", f) for f in os.listdir(os.path.join(BASE, "pages")) if f.endswith(".py")
)
PAGES.insert(0, os.path.join(BASE, "app.py"))

results = []
with mock.patch("src.data.get_history", side_effect=fake_get_history), \
     mock.patch("src.data.get_history_bulk", side_effect=fake_get_history_bulk), \
     mock.patch("src.sens_news.fetch_sens", side_effect=fake_fetch_sens), \
     mock.patch("src.sens_news.fetch_news", side_effect=fake_fetch_news):

    for page_path in PAGES:
        name = os.path.relpath(page_path, BASE)
        try:
            at = AppTest.from_file(page_path, default_timeout=30)
            at.session_state["authenticated"] = True
            at.session_state["username"] = "smoketest"
            at.run()
            # Click any primary buttons once (loads default data views) then re-run.
            for b in list(at.button):
                if getattr(b, "type", None) == "primary" or "run" in (b.label or "").lower() or "load" in (b.label or "").lower():
                    try:
                        b.click().run()
                    except Exception:
                        pass
            if at.exception:
                results.append((name, "FAIL", str(at.exception[0])))
            else:
                results.append((name, "OK", ""))
        except Exception as e:
            results.append((name, "ERROR", f"{type(e).__name__}: {e}\n{traceback.format_exc(limit=3)}"))

print(f"\n{'PAGE':45s} {'STATUS':8s} DETAIL")
print("-" * 100)
n_fail = 0
for name, status, detail in results:
    if status != "OK":
        n_fail += 1
    print(f"{name:45s} {status:8s} {detail[:400]}")

print("-" * 100)
print(f"{len(results) - n_fail}/{len(results)} pages ran cleanly.")
sys.exit(1 if n_fail else 0)

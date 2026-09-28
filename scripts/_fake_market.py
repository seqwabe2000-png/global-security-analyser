"""Synthetic OHLCV generator shared by the offline portfolio tests (no internet needed)."""
import numpy as np
import pandas as pd

_VOL = {"BTC-USD": 0.045, "ETH-USD": 0.055, "SOL-USD": 0.06, "ADA-USD": 0.06, "USDT-USD": 0.001,
        "USDZAR=X": 0.008, "ZARUSD=X": 0.008, "GLD": 0.01}
_CACHE = {}


def fake_history(ticker, n=2600):
    if ticker in _CACHE:
        return _CACHE[ticker]
    rng = np.random.default_rng(abs(hash(ticker)) % (2 ** 32))
    idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=n)
    mkt = np.random.default_rng(42).normal(0.0004, 0.011, n)          # common market factor
    vol = _VOL.get(ticker, rng.uniform(0.012, 0.03))
    beta = 0 if ticker.endswith("=X") or ticker == "USDT-USD" else rng.uniform(0.5, 1.6)
    r = beta * mkt + rng.normal(0.0002, vol, n)
    px = 100 * np.cumprod(1 + r)
    if ticker.endswith("=X"):
        px = 18 * np.cumprod(1 + rng.normal(0.0001, 0.008, n))
    if ticker == "STX40.JO":           # simulate Yahoo cents/rands glitch
        px[1500:1510] = px[1500:1510] / 100
    if ticker in ("SNDK", "GEV"):      # recently listed
        px[: n - 350] = np.nan
    df = pd.DataFrame({"Open": px, "High": px * 1.01, "Low": px * 0.99, "Close": px, "Adj Close": px,
                       "Volume": 1e6}, index=idx).dropna()
    _CACHE[ticker] = df
    return df


def fake_bulk(tickers, period="max", interval="1d", force_refresh=False, progress_cb=None):
    return {t: fake_history(t) for t in tickers if t not in ("FAKE1",)}

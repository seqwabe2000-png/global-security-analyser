"""
Data layer: JSE stock universe + price history via yfinance, with a local
on-disk cache so the app doesn't re-hit Yahoo Finance on every rerun.

NOTE: this module was developed in a sandboxed environment with no route to
Yahoo Finance, so the live yfinance calls below could not be exercised
end-to-end during development. Run `python3 scripts/test_data_connection.py`
after installing requirements to confirm connectivity on your machine. The
code fails soft everywhere (missing tickers are logged and skipped, never
raised to the UI) so a handful of bad/illiquid tickers won't break the app.
"""
import json
import os
import time
from datetime import datetime, timedelta

import pandas as pd
import streamlit as st
import yfinance as yf
from dateutil.relativedelta import relativedelta

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE, "data")
CACHE_DIR = os.path.join(DATA_DIR, "cache")
UNIVERSE_PATH = os.path.join(DATA_DIR, "jse_universe.csv")
CACHE_META_PATH = os.path.join(CACHE_DIR, "_meta.json")

os.makedirs(CACHE_DIR, exist_ok=True)

# JSE benchmark indices (Yahoo Finance tickers), used for rolling beta/correlation
BENCHMARKS = {
    "JSE All Share": "^J203.JO",
    "JSE Top 40": "^J200.JO",
}

CHUNK_SIZE = 40
CHUNK_SLEEP_SECONDS = 1.5
HISTORY_TTL_HOURS = 6  # how long a cached price history is considered fresh


# --------------------------------------------------------------------------
# Universe
# --------------------------------------------------------------------------
@st.cache_data(show_spinner=False)
def load_universe() -> pd.DataFrame:
    df = pd.read_csv(UNIVERSE_PATH)
    df["market_cap_zar"] = pd.to_numeric(df["market_cap_zar"], errors="coerce")
    return df


def universe_tickers() -> list:
    return load_universe()["yf_ticker"].tolist()


# --------------------------------------------------------------------------
# Disk cache helpers
# --------------------------------------------------------------------------
def _cache_path(ticker: str, interval: str) -> str:
    safe = ticker.replace("/", "_")
    return os.path.join(CACHE_DIR, f"{safe}__{interval}.parquet")


def _load_meta() -> dict:
    if os.path.exists(CACHE_META_PATH):
        try:
            with open(CACHE_META_PATH) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_meta(meta: dict):
    with open(CACHE_META_PATH, "w") as f:
        json.dump(meta, f)


def _is_fresh(ticker: str, interval: str, meta: dict) -> bool:
    key = f"{ticker}__{interval}"
    ts = meta.get(key)
    if ts is None:
        return False
    fetched = datetime.fromisoformat(ts)
    return datetime.now() - fetched < timedelta(hours=HISTORY_TTL_HOURS)


def _read_cached(ticker: str, interval: str):
    path = _cache_path(ticker, interval)
    if os.path.exists(path):
        try:
            return pd.read_parquet(path)
        except Exception:
            return None
    return None


def _write_cache(ticker: str, interval: str, df: pd.DataFrame, meta: dict):
    df.to_parquet(_cache_path(ticker, interval))
    meta[f"{ticker}__{interval}"] = datetime.now().isoformat()


# --------------------------------------------------------------------------
# Price history
# --------------------------------------------------------------------------
def _normalise_history(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure standard column set + ascending-date DatetimeIndex.

    Defensive against yfinance version quirks: depending on version and on
    whether a batch download partially failed, the frame handed in here can
    still carry MultiIndex columns, or be missing a field outright (seen in
    the wild: a "single-ticker" chunk that still comes back with
    (ticker, field) MultiIndex columns instead of flat ones). Rather than
    raising on any of that, collapse/backfill what we can and only give up
    (return empty) if there's no Close price to work with at all."""
    if df is None or df.empty:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Adj Close", "Volume"])
    df = df.copy()

    if isinstance(df.columns, pd.MultiIndex):
        # Collapse to whichever level actually holds field names like "Close".
        field_names = {"Open", "High", "Low", "Close", "Adj Close", "Volume"}
        level = next(
            (lvl for lvl in range(df.columns.nlevels) if field_names & set(df.columns.get_level_values(lvl))),
            df.columns.nlevels - 1,
        )
        df.columns = df.columns.get_level_values(level)
        df = df.loc[:, ~df.columns.duplicated()]

    if "Adj Close" not in df.columns and "Close" in df.columns:
        df["Adj Close"] = df["Close"]

    if "Close" not in df.columns:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Adj Close", "Volume"])

    for col in ["Open", "High", "Low", "Volume"]:
        if col not in df.columns:
            df[col] = df["Close"] if col != "Volume" else 0

    df = df[["Open", "High", "Low", "Close", "Adj Close", "Volume"]]
    df.index = pd.to_datetime(df.index).tz_localize(None)
    df = df.sort_index()
    df = df[~df.index.duplicated(keep="last")]
    return df.dropna(how="all", subset=["Close"])


# --------------------------------------------------------------------------
# Period slicing
#
# The cache is keyed by ticker + interval only (not period) -- so every
# fetch below always pulls and caches the FULL available history from
# Yahoo, regardless of what `period` the caller asked for, and then slices
# down to that period locally. Without this, a stock first fetched via a
# short-period page (e.g. Charts' default "2y") would get its full history
# cached, and a later "max"-period request (e.g. Relative Performance)
# would see that cache as "fresh" and silently keep serving only 2 years of
# data until the 6-hour TTL expired -- which is exactly the "data only
# goes back to 2024" symptom this fixes.
# --------------------------------------------------------------------------
_PERIOD_RELDELTA = {
    "1d": relativedelta(days=1), "5d": relativedelta(days=5),
    "1mo": relativedelta(months=1), "3mo": relativedelta(months=3),
    "6mo": relativedelta(months=6), "18mo": relativedelta(months=18),
    "1y": relativedelta(years=1), "2y": relativedelta(years=2),
    "3y": relativedelta(years=3), "5y": relativedelta(years=5),
    "10y": relativedelta(years=10),
}


def _slice_period(df: pd.DataFrame, period: str) -> pd.DataFrame:
    if df is None or df.empty or period in (None, "max"):
        return df
    if period == "ytd":
        cutoff = pd.Timestamp(df.index.max().year, 1, 1)
    else:
        delta = _PERIOD_RELDELTA.get(period)
        if delta is None:
            return df  # unrecognised period string -- return full history rather than guess
        cutoff = df.index.max() - delta
    sliced = df[df.index >= cutoff]
    return sliced if not sliced.empty else df


def get_history(ticker: str, period: str = "5y", interval: str = "1d", force_refresh: bool = False) -> pd.DataFrame:
    """Single-ticker OHLCV history, disk-cached. The cache always holds the
    fullest history available (see _slice_period above); `period` only
    controls how much of it is returned to this particular caller."""
    meta = _load_meta()
    if not force_refresh and _is_fresh(ticker, interval, meta):
        cached = _read_cached(ticker, interval)
        if cached is not None and not cached.empty:
            return _slice_period(cached, period)

    try:
        raw = yf.Ticker(ticker).history(period="max", interval=interval, auto_adjust=False)
    except Exception as e:
        cached = _read_cached(ticker, interval)
        if cached is not None:
            return _slice_period(cached, period)
        print(f"[data] history fetch failed for {ticker}: {e}")
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Adj Close", "Volume"])

    df = _normalise_history(raw)
    if not df.empty:
        _write_cache(ticker, interval, df, meta)
        _save_meta(meta)
    elif not force_refresh:
        # "max" fetch came back empty (e.g. a transient hiccup) -- fall back
        # to whatever's cached rather than reporting no data at all.
        cached = _read_cached(ticker, interval)
        if cached is not None and not cached.empty:
            return _slice_period(cached, period)
    return _slice_period(df, period)


def get_history_bulk(tickers: list, period: str = "1y", interval: str = "1d",
                      force_refresh: bool = False, progress_cb=None) -> dict:
    """Batch OHLCV fetch for many tickers with disk caching + chunking so we
    don't hammer Yahoo Finance with 250+ individual requests.

    Like get_history, this always fetches/caches the FULL available history
    per ticker and slices to `period` locally -- see the note above
    _slice_period for why (avoids a short-period request permanently
    "poisoning" the cache for later long-period requests on the same
    ticker).

    Returns {ticker: DataFrame}. Tickers that fail to download are simply
    omitted (never raises).
    """
    meta = _load_meta()
    results = {}
    to_fetch = []

    for t in tickers:
        if not force_refresh and _is_fresh(t, interval, meta):
            cached = _read_cached(t, interval)
            if cached is not None and not cached.empty:
                results[t] = _slice_period(cached, period)
                continue
        to_fetch.append(t)

    total_chunks = max(1, (len(to_fetch) + CHUNK_SIZE - 1) // CHUNK_SIZE)
    for i in range(0, len(to_fetch), CHUNK_SIZE):
        chunk = to_fetch[i : i + CHUNK_SIZE]
        chunk_idx = i // CHUNK_SIZE + 1
        if progress_cb:
            progress_cb(chunk_idx, total_chunks)
        try:
            raw = yf.download(
                tickers=chunk,
                period="max",
                interval=interval,
                group_by="ticker",
                auto_adjust=False,
                threads=True,
                progress=False,
            )
        except Exception as e:
            print(f"[data] bulk download failed for chunk {chunk}: {e}")
            raw = None

        fetched_this_chunk = set()
        if raw is not None and not raw.empty:
            # Don't assume a single-ticker chunk means flat (non-MultiIndex)
            # columns -- some yfinance versions still return (ticker, field)
            # MultiIndex columns even for a chunk of one. Check the actual
            # shape instead of inferring it from len(chunk).
            if isinstance(raw.columns, pd.MultiIndex):
                for t in chunk:
                    try:
                        sub = raw[t]
                    except KeyError:
                        continue
                    df = _normalise_history(sub)
                    if not df.empty:
                        results[t] = _slice_period(df, period)
                        fetched_this_chunk.add(t)
                        _write_cache(t, interval, df, meta)
            else:
                df = _normalise_history(raw)
                if not df.empty:
                    results[chunk[0]] = _slice_period(df, period)
                    fetched_this_chunk.add(chunk[0])
                    _write_cache(chunk[0], interval, df, meta)

        # Anything in this chunk that didn't come back (transient hiccup,
        # not necessarily "no data") -- fall back to a stale cache entry
        # rather than dropping it outright.
        for t in chunk:
            if t in fetched_this_chunk:
                continue
            cached = _read_cached(t, interval)
            if cached is not None and not cached.empty:
                results[t] = _slice_period(cached, period)

        if i + CHUNK_SIZE < len(to_fetch):
            time.sleep(CHUNK_SLEEP_SECONDS)

    _save_meta(meta)
    missing = [t for t in tickers if t not in results]
    if missing:
        print(f"[data] no data for {len(missing)} tickers: {missing[:20]}{'...' if len(missing) > 20 else ''}")
    return results


def resample_ohlc(df: pd.DataFrame, freq: str) -> pd.DataFrame:
    """freq: 'W' (weekly, Fri close) or 'M' (monthly) or 'Q' (quarterly)."""
    if df.empty:
        return df
    agg = {
        "Open": "first",
        "High": "max",
        "Low": "min",
        "Close": "last",
        "Adj Close": "last",
        "Volume": "sum",
    }
    freq_map = {"D": "D", "W": "W-FRI", "M": "ME", "Q": "QE"}
    return df.resample(freq_map.get(freq, freq)).agg(agg).dropna(how="all")


def last_price_change(df: pd.DataFrame):
    """Return (last_close, pct_change_vs_prev_close) or (None, None)."""
    closes = df["Close"].dropna()
    if len(closes) < 2:
        return (closes.iloc[-1] if len(closes) else None, None)
    last, prev = closes.iloc[-1], closes.iloc[-2]
    pct = (last - prev) / prev * 100 if prev else None
    return last, pct


def cache_status() -> dict:
    meta = _load_meta()
    if not meta:
        return {"count": 0, "oldest": None, "newest": None}
    times = [datetime.fromisoformat(v) for v in meta.values()]
    return {"count": len(meta), "oldest": min(times), "newest": max(times)}

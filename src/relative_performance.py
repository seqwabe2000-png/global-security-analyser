"""
Relative-performance helpers: normalized (rebased-to-0%) price paths for
stocks, GICS sectors, industries/subsectors, and JSE benchmark indices --
the "Koyfin-style" comparison chart used by pages/9 and pages/10.

Index data caveat (read this before trusting a number here)
-------------------------------------------------------------
There's no free official feed for the ~30+ narrower FTSE/JSE sector and
industry indices. What's below is a best-effort candidate list assembled
from web research (this module's dev sandbox has no live route to Yahoo
Finance, so none of these candidate tickers were actually confirmed to
return data -- only ^J203.JO and ^J200.JO have been confirmed working, on
your machine, via scripts/test_data_connection.py). Two extra wrinkles:

1. Some FTSE/JSE indices only seem to exist on Yahoo Finance as their
   London cross-listing (a ".L" ticker, GBP-quoted) rather than a ".JO"
   ticker. The *index level* (points) for a FTSE index is normally the
   same regardless of listing currency suffix, but this hasn't been
   confirmed live, so treat ".L" results with a little extra caution --
   compare a couple of data points against a source you trust before
   relying on it for a real decision.
2. Whatever isn't found on Yahoo (or fails to return data on your
   machine) automatically falls back to a **constructed index**: the
   market-cap-weighted average return of that sector/industry's actual
   constituent stocks in your universe (weights are each stock's latest
   known market cap, not true point-in-time weighting -- see
   `cap_weighted_index` below). This always works (it's built from data
   you already have), just isn't the officially published index value.
   The app always labels which kind you're looking at.

Edit the candidate dictionaries below freely as you confirm real tickers
on your own machine -- `scripts/test_data_connection.py` includes a
labeled block for exactly this purpose.
"""
from dateutil.relativedelta import relativedelta
import numpy as np
import pandas as pd

from src import data
from src import universe as uni

# --------------------------------------------------------------------------
# Best-effort Yahoo Finance ticker candidates (see caveats above)
# --------------------------------------------------------------------------
BROAD_INDEX_CANDIDATES = {
    "JSE All Share": ["^J203.JO"],          # confirmed working
    "JSE Top 40": ["^J200.JO"],             # confirmed working
    "JSE Mid Cap": ["J201.L"],              # unverified -- London cross-listing
    "JSE Small Cap": ["J202.L"],            # unverified -- London cross-listing
}

SECTOR_INDEX_CANDIDATES = {
    "Financials": ["^J580.JO"],             # unverified
    "Real Estate": ["^J253.JO", "J253.L"],  # unverified (SA Listed Property)
    "Industrials": ["J520.L"],              # unverified -- London cross-listing
}

INDUSTRY_INDEX_CANDIDATES = {
    "Banks": ["J835.L"],                    # unverified -- London cross-listing
    "Diversified Mining": ["J177.L"],       # unverified (SA Mining index)
    "Gold Mining": ["J150.L"],              # unverified -- London cross-listing
}

# Which universe subset each broad index falls back to constructing from,
# if its Yahoo candidates all fail.
BROAD_FALLBACK = {
    "JSE All Share": lambda universe_df: universe_df,
    "JSE Top 40": lambda universe_df: universe_df.sort_values("market_cap_usd_bn", ascending=False).head(40),
    "JSE Mid Cap": lambda universe_df: universe_df[universe_df["market_cap_tier"] == "Mid Cap"],
    "JSE Small Cap": lambda universe_df: universe_df[universe_df["market_cap_tier"] == "Small Cap"],
}


def _other_market_fallback(market_name):
    """Fallback constructed index for a non-JSE market: cap-weighted average
    of that market's own equities in the global universe, regardless of
    what subset of the universe the calling page happens to have loaded."""
    def _fn(_universe_df):
        full = uni.load_instruments()
        return full[(full["asset_class"] == "Equity") & (full["market"] == market_name)]
    return _fn


# Every other equity market's own broad benchmark index (real Yahoo ticker,
# with a cap-weighted-constituent fallback) -- lets Relative Performance and
# Pairs Trade overlay e.g. the S&P 500 or FTSE 100 alongside JSE lines.
for _mkt, _ticker in uni.MARKET_BENCHMARK.items():
    if _mkt == "South Africa":
        continue  # already covered by the JSE-specific entries above
    _label = f"{_mkt} (Broad Index)"
    BROAD_INDEX_CANDIDATES[_label] = [_ticker]
    BROAD_FALLBACK[_label] = _other_market_fallback(_mkt)

TIMEFRAMES = ["1D", "5D", "MTD", "1M", "QTD", "6M", "YTD", "1Y", "3Y", "5Y", "10Y", "MAX"]


# --------------------------------------------------------------------------
# Core series helpers
# --------------------------------------------------------------------------
def resolve_index_ticker(candidates, min_points: int = 20):
    """Try each candidate ticker (in order) via the normal cached history
    fetch. Returns (close_series, ticker_used) for the first one that
    returns usable data, or (None, None) if all fail."""
    for t in candidates:
        df = data.get_history(t, period="max", interval="1d")
        if df is not None and not df.empty and len(df) >= min_points:
            return df["Close"], t
    return None, None


MAX_DAILY_MOVE = 5.0  # clip any single stock's daily return to [-95%, +500%]


def cap_weighted_index(hist: dict, subset: pd.DataFrame, price_col: str = "Adj Close") -> pd.Series:
    """Constructed benchmark: market-cap-weighted average daily return across
    the given constituents' cached histories, compounded into an index level
    series starting at 100. `subset` must have `yf_ticker` and
    `market_cap_usd_bn` columns -- weights are each instrument's latest known
    (approximate) market cap (a static snapshot, not true point-in-time
    cap-weighting, but far more representative of a real sector/industry
    index than treating a $500bn company the same as a $2bn small-cap).
    A constituent missing a market cap (including every non-equity asset
    class, where "market cap" isn't a concept -- see src/universe.py) falls
    back to the average cap of the others, which in practice makes the
    non-equity case equal-weighted. Weights are renormalized each day
    across only the constituents that actually have a return that day;
    days where none of the constituents have data are treated as flat (0%
    return) rather than dropped, so the series stays aligned to the full
    calendar.

    Uses Adj Close (dividend/split-adjusted) rather than raw Close, and
    clips each stock's daily return to a sane band before averaging. Both
    guard against the same real failure mode: one illiquid JSE constituent
    with an unadjusted stock split or a bad data tick can otherwise produce
    a single-day "return" of thousands or millions of percent for that one
    stock, which a weighted average -- and worse, the cumulative product
    that turns daily returns into an index level -- would then bake into
    the whole sector/industry line permanently instead of just that one
    day."""
    tickers = subset["yf_ticker"].tolist()
    returns = {}
    for t in tickers:
        df = hist.get(t)
        if df is None or df.empty:
            continue
        col = price_col if price_col in df.columns else "Close"
        returns[t] = df[col].pct_change().clip(lower=-0.95, upper=MAX_DAILY_MOVE)
    if not returns:
        return pd.Series(dtype=float)
    combined = pd.concat(returns, axis=1).sort_index()

    weights = pd.to_numeric(subset.set_index("yf_ticker")["market_cap_usd_bn"], errors="coerce")
    weights = weights.reindex(combined.columns)
    fallback = weights.mean(skipna=True)
    weights = weights.fillna(fallback if fallback == fallback and fallback > 0 else 1.0)
    weights = weights.clip(lower=0)

    weight_matrix = pd.DataFrame(
        np.tile(weights.values, (len(combined), 1)), index=combined.index, columns=combined.columns
    )
    weight_matrix = weight_matrix.where(combined.notna(), 0.0)
    weight_sum = weight_matrix.sum(axis=1)
    weighted_sum = (combined.fillna(0.0) * weight_matrix).sum(axis=1)
    avg_return = (weighted_sum / weight_sum.replace(0, np.nan)).fillna(0.0)
    return (1 + avg_return).cumprod() * 100


# --------------------------------------------------------------------------
# Cyclical vs. defensive sector rotation gauge (Market Breadth page)
# --------------------------------------------------------------------------
# Standard sector-rotation grouping: "cyclical" sectors swing more with the
# economic cycle (spending on cars/retail/travel, industrial output,
# commodity prices, credit growth, building activity, tech capex); "defensive"
# sectors keep selling roughly the same amount in a downturn (food, medicine,
# power, phone/data bills) so they tend to hold up better when the economy
# or the market is under stress. There's no single official JSE version of
# this split -- this mirrors the grouping commonly used by index providers
# (e.g. State Street/Fidelity sector-rotation frameworks) applied to the
# GICS sectors present in this app's universe.
CYCLICAL_SECTORS = [
    "Consumer Discretionary",
    "Financials",
    "Industrials",
    "Materials",
    "Information Technology",
    "Real Estate",
    "Energy",
]
DEFENSIVE_SECTORS = [
    "Consumer Staples",
    "Health Care",
    "Utilities",
    "Communication Services",
]


def cyclical_defensive_ratio(universe: pd.DataFrame, hist: dict) -> dict:
    """Builds a cap-weighted index of CYCLICAL_SECTORS and a cap-weighted
    index of DEFENSIVE_SECTORS from `hist` (as returned by
    data.get_history_bulk for the relevant tickers), then divides one by the
    other and rebases the ratio to 100 at the start of the available window.

    Reads as a classic risk-on/risk-off gauge: the ratio rising means
    cyclical stocks are outperforming defensive ones (often coincides with
    "risk-on"/economic-optimism conditions); the ratio falling means
    defensives are outperforming (often "risk-off"/flight-to-safety
    conditions). It says nothing on its own about the *level* of the market,
    only which style of sector is leading.

    Returns a dict with keys: "ratio" (the rebased ratio Series, empty if it
    couldn't be computed), "cyclical" / "defensive" (each sector group's own
    cap-weighted index level, for reference), "cyclical_sectors" /
    "defensive_sectors" (the sector lists used), and "n_cyclical" /
    "n_defensive" (how many universe constituents fed each side).
    """
    cyc_subset = universe[universe["gics_sector"].isin(CYCLICAL_SECTORS)]
    def_subset = universe[universe["gics_sector"].isin(DEFENSIVE_SECTORS)]

    cyc_index = cap_weighted_index(hist, cyc_subset)
    def_index = cap_weighted_index(hist, def_subset)

    result = {
        "ratio": pd.Series(dtype=float),
        "cyclical": cyc_index,
        "defensive": def_index,
        "cyclical_sectors": CYCLICAL_SECTORS,
        "defensive_sectors": DEFENSIVE_SECTORS,
        "n_cyclical": len(cyc_subset),
        "n_defensive": len(def_subset),
    }
    if cyc_index.empty or def_index.empty:
        return result

    combined = pd.concat({"cyc": cyc_index, "def": def_index}, axis=1).dropna()
    if combined.empty:
        return result

    raw_ratio = combined["cyc"] / combined["def"]
    raw_ratio = raw_ratio.replace([np.inf, -np.inf], np.nan).dropna()
    if raw_ratio.empty:
        return result

    result["ratio"] = raw_ratio / raw_ratio.iloc[0] * 100
    return result


def normalize_pct(series: pd.Series) -> pd.Series:
    """Rebase a price/level series to cumulative % change from its first
    valid value -- matches the 0%-at-left-edge convention of the reference
    normalized-performance charts."""
    s = series.dropna()
    if s.empty:
        return s
    base = s.iloc[0]
    if base == 0 or pd.isna(base):
        return pd.Series(dtype=float)
    return (s / base - 1) * 100


def slice_to_timeframe(series: pd.Series, timeframe: str) -> pd.Series:
    """Slice a series (ascending DatetimeIndex) down to the requested
    lookback window, anchored on the series' own last date (not necessarily
    today, e.g. if data is a little stale)."""
    if series.empty:
        return series
    end = series.index.max()
    if timeframe == "MAX":
        return series
    if timeframe == "1D":
        cutoff = series.index[series.index < end][-1] if (series.index < end).any() else series.index[0]
        return series[series.index >= cutoff]
    if timeframe == "5D":
        cutoff = end - relativedelta(days=9)
    elif timeframe == "MTD":
        cutoff = pd.Timestamp(end.year, end.month, 1) - relativedelta(days=1)
    elif timeframe == "1M":
        cutoff = end - relativedelta(months=1)
    elif timeframe == "QTD":
        q_start_month = 3 * ((end.month - 1) // 3) + 1
        cutoff = pd.Timestamp(end.year, q_start_month, 1) - relativedelta(days=1)
    elif timeframe == "6M":
        cutoff = end - relativedelta(months=6)
    elif timeframe == "YTD":
        cutoff = pd.Timestamp(end.year - 1, 12, 31)
    elif timeframe == "1Y":
        cutoff = end - relativedelta(years=1)
    elif timeframe == "3Y":
        cutoff = end - relativedelta(years=3)
    elif timeframe == "5Y":
        cutoff = end - relativedelta(years=5)
    elif timeframe == "10Y":
        cutoff = end - relativedelta(years=10)
    else:
        return series
    sliced = series[series.index >= cutoff]
    return sliced if len(sliced) >= 2 else series


# --------------------------------------------------------------------------
# Line resolution: given a "thing to plot" (a stock, a sector, an industry,
# or a broad index), get its normalized % line + a label describing the
# data source actually used.
# --------------------------------------------------------------------------
def broad_index_line(name: str, universe, hist_lookup):
    candidates = BROAD_INDEX_CANDIDATES.get(name, [])
    series, ticker = resolve_index_ticker(candidates)
    if series is not None:
        return series, f"Yahoo Finance ({ticker})"
    subset = BROAD_FALLBACK.get(name, lambda uni: uni)(universe)
    tickers = subset["yf_ticker"].tolist()
    hist = hist_lookup(tickers)
    return cap_weighted_index(hist, subset), f"Constructed ({len(tickers)} stocks, cap-weighted)"


def sector_line(sector: str, universe, hist_lookup):
    candidates = SECTOR_INDEX_CANDIDATES.get(sector, [])
    series, ticker = resolve_index_ticker(candidates)
    if series is not None:
        return series, f"Yahoo Finance ({ticker})"
    subset = universe[universe["gics_sector"] == sector]
    tickers = subset["yf_ticker"].tolist()
    hist = hist_lookup(tickers)
    return cap_weighted_index(hist, subset), f"Constructed ({len(tickers)} stocks, cap-weighted)"


def industry_line(sector: str, industry: str, universe, hist_lookup):
    candidates = INDUSTRY_INDEX_CANDIDATES.get(industry, [])
    series, ticker = resolve_index_ticker(candidates)
    if series is not None:
        return series, f"Yahoo Finance ({ticker})"
    subset = universe[(universe["gics_sector"] == sector) & (universe["industry"] == industry)]
    tickers = subset["yf_ticker"].tolist()
    hist = hist_lookup(tickers)
    return cap_weighted_index(hist, subset), f"Constructed ({len(tickers)} stocks, cap-weighted)"


def stock_line(ticker: str, hist_lookup):
    hist = hist_lookup([ticker])
    df = hist.get(ticker)
    if df is None or df.empty:
        return pd.Series(dtype=float), "No data"
    col = "Adj Close" if "Adj Close" in df.columns else "Close"
    return df[col], "Yahoo Finance (price)"

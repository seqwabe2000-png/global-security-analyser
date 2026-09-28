"""
Pairs-trade statistics: spread/ratio, rolling correlation, rolling z-score
of the spread, and a cointegration + mean-reversion half-life check.

NOTE: like the rest of this app, these formulas were written and unit
tested against synthetic data in a network-sandboxed dev environment --
the math itself (rolling stats, OLS, Engle-Granger cointegration via
statsmodels) is standard and doesn't depend on live data, but you're
encouraged to sanity-check a result or two against a source you trust
before actually trading on it. This is not investment advice.
"""
import numpy as np
import pandas as pd

try:
    from statsmodels.tsa.stattools import coint
except ImportError:  # pragma: no cover
    coint = None


def price_ratio(price_a: pd.Series, price_b: pd.Series) -> pd.Series:
    """Aligned A/B price ratio (the classic 'spread' for a pairs trade)."""
    aligned = pd.concat({"a": price_a, "b": price_b}, axis=1).dropna()
    if aligned.empty:
        return pd.Series(dtype=float)
    return (aligned["a"] / aligned["b"]).rename("ratio")


def rolling_zscore(series: pd.Series, window: int) -> pd.Series:
    mean = series.rolling(window=window, min_periods=window).mean()
    std = series.rolling(window=window, min_periods=window).std()
    return (series - mean) / std.replace(0, np.nan)


def spread_returns(returns_a: pd.Series, returns_b: pd.Series, weight_a: float = 0.5, weight_b: float = 0.5) -> pd.Series:
    """Dollar-neutral-style spread return: weight_a * A's return minus
    weight_b * B's return (weights are each leg's share of gross exposure,
    e.g. long_exposure / (long_exposure + short_exposure)). Matches the
    'Spread Returns' column in DoR_Stops_and_Targets.xlsx's spread sheet --
    a positive value means the long-A/short-B trade made money that period."""
    aligned = pd.concat({"a": returns_a, "b": returns_b}, axis=1).dropna()
    if aligned.empty:
        return pd.Series(dtype=float)
    return (weight_a * aligned["a"] - weight_b * aligned["b"]).rename("spread_return")


def rolling_correlation(returns_a: pd.Series, returns_b: pd.Series, window: int) -> pd.Series:
    aligned = pd.concat({"a": returns_a, "b": returns_b}, axis=1).dropna()
    if aligned.empty:
        return pd.Series(dtype=float)
    return aligned["a"].rolling(window=window, min_periods=window).corr(aligned["b"])


def half_life(spread: pd.Series):
    """Mean-reversion half-life (in trading periods) from an
    Ornstein-Uhlenbeck-style fit: regress spread(t) - spread(t-1) on
    spread(t-1). Returns None if the spread doesn't look mean-reverting
    (i.e. the fitted slope isn't negative) or there isn't enough data."""
    s = spread.dropna()
    if len(s) < 30:
        return None
    lagged = s.shift(1).dropna()
    delta = s.diff().dropna()
    aligned = pd.concat({"lagged": lagged, "delta": delta}, axis=1).dropna()
    if len(aligned) < 20 or aligned["lagged"].std() == 0:
        return None
    slope, intercept = np.polyfit(aligned["lagged"], aligned["delta"], 1)
    if slope >= 0:
        return None  # not mean-reverting
    return -np.log(2) / slope


def cointegration_test(price_a: pd.Series, price_b: pd.Series):
    """Engle-Granger two-step cointegration test (statsmodels). Returns a
    dict with the test statistic, p-value, and a plain-language verdict, or
    a dict with an 'error' key if statsmodels isn't installed or there
    isn't enough overlapping data."""
    if coint is None:
        return {"error": "statsmodels is not installed -- run `pip install -r requirements.txt` to get it."}
    aligned = pd.concat({"a": price_a, "b": price_b}, axis=1).dropna()
    if len(aligned) < 40:
        return {"error": "Not enough overlapping price history for a reliable cointegration test."}
    try:
        tstat, pvalue, _crit_values = coint(aligned["a"], aligned["b"])
    except Exception as e:
        return {"error": f"Cointegration test failed: {e}"}
    if pvalue < 0.05:
        verdict = "Likely cointegrated -- the spread has historically tended to mean-revert."
    elif pvalue < 0.10:
        verdict = "Weak evidence of cointegration -- borderline, treat with caution."
    else:
        verdict = "No significant evidence of cointegration -- the spread may drift indefinitely rather than mean-revert."
    return {"tstat": tstat, "pvalue": pvalue, "verdict": verdict}

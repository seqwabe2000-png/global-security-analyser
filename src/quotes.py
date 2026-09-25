"""
Shared "quote snapshot table" builder -- the Name/Symbol/Last/Open/High/Low/
Chg/Chg%/Vol table style used across World Markets, US Sector Breadth,
Crypto, Commodities & Currencies, and Bonds & Rates. One place for this so
every asset-class page renders the same table shape/behaviour.
"""
import pandas as pd
import streamlit as st

from src import data


def snapshot_table(name_ticker_pairs: dict, period: str = "5d") -> pd.DataFrame:
    """name_ticker_pairs: {display_name: yf_ticker}. Returns a DataFrame with
    Name, Symbol, Last, Open, High, Low, Chg, Chg %, Vol -- one row per
    ticker that returned data (tickers with no data are silently skipped,
    same fail-soft philosophy as the rest of the app)."""
    tickers = list(name_ticker_pairs.values())
    hist = data.get_history_bulk(tickers, period=period, interval="1d")

    rows = []
    for name, ticker in name_ticker_pairs.items():
        df = hist.get(ticker)
        if df is None or df.empty:
            continue
        last_row = df.iloc[-1]
        prev_close = df["Close"].iloc[-2] if len(df) >= 2 else None
        chg = (last_row["Close"] - prev_close) if prev_close is not None else None
        chg_pct = (chg / prev_close * 100) if chg is not None and prev_close else None
        rows.append({
            "Name": name,
            "Symbol": ticker,
            "Last": last_row["Close"],
            "Open": last_row["Open"],
            "High": last_row["High"],
            "Low": last_row["Low"],
            "Chg.": chg,
            "Chg. %": chg_pct,
            "Vol.": last_row.get("Volume"),
        })
    return pd.DataFrame(rows)


def _fmt_vol(v):
    if v is None or v != v:
        return "—"
    v = float(v)
    if v >= 1e9:
        return f"{v / 1e9:.2f}B"
    if v >= 1e6:
        return f"{v / 1e6:.2f}M"
    if v >= 1e3:
        return f"{v / 1e3:.2f}K"
    return f"{v:.0f}"


def style_snapshot(df: pd.DataFrame, up_color: str, down_color: str):
    """Colour Chg./Chg. % green/red like the reference screenshots, and
    format volume with M/B suffixes. Returns a pandas Styler ready for
    st.dataframe(...)."""
    if df.empty:
        return df

    def _color(v):
        if v is None or v != v:
            return ""
        return f"color: {up_color}; font-weight: 600" if v >= 0 else f"color: {down_color}; font-weight: 600"

    fmt = {
        "Last": "{:,.2f}", "Open": "{:,.2f}", "High": "{:,.2f}", "Low": "{:,.2f}",
        "Chg.": "{:+,.2f}", "Chg. %": "{:+.2f}%", "Vol.": _fmt_vol,
    }
    styler = df.style.format(fmt)
    try:
        styled = styler.map(_color, subset=["Chg.", "Chg. %"])
    except AttributeError:
        styled = styler.applymap(_color, subset=["Chg.", "Chg. %"])
    return styled

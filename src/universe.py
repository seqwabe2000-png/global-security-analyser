"""
Global multi-asset-class, multi-market instrument universe.

This is the layer that turns the app from "JSE stocks only" into "any
instrument Yahoo Finance covers". Every page that used to call
`data.load_universe()` (JSE-only) should instead call
`universe.load_instruments()` and then narrow it down with
`universe.picker(...)` (a ready-made sidebar/inline filter widget) or
`universe.filter_instruments(...)` (the same filtering logic without any
UI, for use in cached helper functions).

Schema (see scripts/build_global_universe.py for how it's built):
    asset_class        "Equity" | "Crypto" | "Commodity" | "Currency" | "Bond/Rate"
    market             "South Africa", "United States", "Global", ...
    symbol             short code, no exchange suffix
    yf_ticker          the actual Yahoo Finance ticker
    name               display name
    gics_sector        GICS sector for equities; a comparable *category*
                        grouping for every other asset class. The UI always
                        labels this control "Sector / Category" so it reads
                        sensibly no matter which asset class is selected.
    industry           finer sub-grouping, same idea.
    currency           quote currency.
    market_cap_tier    Mega/Large/Mid/Small/Micro Cap, relative to that
                        instrument's own market. "--" where N/A.
    market_cap_usd_bn  rough USD market cap for sorting only, or NaN.
"""
import os

import pandas as pd
import streamlit as st

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INSTRUMENTS_PATH = os.path.join(BASE, "data", "universe", "instruments.csv")

ASSET_CLASS_ORDER = ["Equity", "Crypto", "Commodity", "Currency", "Bond/Rate", "Mutual Fund"]
EQUITY_MARKET_ORDER = [
    "South Africa", "United States", "United Kingdom", "Germany", "Japan",
    "Canada", "Australia", "India", "Brazil", "China/Hong Kong",
]

# --------------------------------------------------------------------------
# World / benchmark indices (used by the World Markets overview page and as
# overlay lines on Relative Performance / Charts).
# --------------------------------------------------------------------------
WORLD_INDICES = {
    "S&P 500": "^GSPC",
    "Dow Jones Industrial Average": "^DJI",
    "Nasdaq Composite": "^IXIC",
    "Russell 2000": "^RUT",
    "FTSE 100": "^FTSE",
    "DAX": "^GDAXI",
    "CAC 40": "^FCHI",
    "Euro Stoxx 50": "^STOXX50E",
    "Nikkei 225": "^N225",
    "Hang Seng": "^HSI",
    "Shanghai Composite": "000001.SS",
    "Nifty 50": "^NSEI",
    "Bovespa": "^BVSP",
    "S&P/TSX Composite": "^GSPTSE",
    "S&P/ASX 200": "^AXJO",
    "JSE All Share": "^J203.JO",
    "JSE Top 40": "^J200.JO",
}

# The benchmark index used to overlay/compare each equity market.
MARKET_BENCHMARK = {
    "South Africa": "^J203.JO",
    "United States": "^GSPC",
    "United Kingdom": "^FTSE",
    "Germany": "^GDAXI",
    "Japan": "^N225",
    "Canada": "^GSPTSE",
    "Australia": "^AXJO",
    "India": "^NSEI",
    "Brazil": "^BVSP",
    "China/Hong Kong": "^HSI",
}

# US SPDR Select Sector ETFs -- real, tradable sector proxies (matches the
# reference screenshot table exactly: name, symbol, then live OHLC/chg/vol).
US_SECTOR_ETFS = {
    "Technology Select Sector SPDR": "XLK",
    "Financial Select Sector SPDR": "XLF",
    "Health Care Select Sector SPDR": "XLV",
    "Consumer Discretionary Select Sector SPDR": "XLY",
    "Consumer Staples Select Sector SPDR": "XLP",
    "Energy Select Sector SPDR": "XLE",
    "Industrial Select Sector SPDR": "XLI",
    "Materials Select Sector SPDR": "XLB",
    "Utilities Select Sector SPDR": "XLU",
    "Real Estate Select Sector SPDR": "XLRE",
    "Communication Services Select Sector SPDR": "XLC",
}
US_BROAD_ETFS = {
    "SPDR S&P 500": "SPY",
    "Invesco QQQ Trust": "QQQ",
    "SPDR Dow Jones Industrial Average": "DIA",
    "iShares Russell 2000": "IWM",
}
# GICS sector name -> its SPDR ETF ticker (pairs "real" sector-ETF
# performance with "constructed" breadth from the constituent list).
US_SECTOR_TO_ETF = {
    "Information Technology": "XLK", "Financials": "XLF", "Health Care": "XLV",
    "Consumer Discretionary": "XLY", "Consumer Staples": "XLP", "Energy": "XLE",
    "Industrials": "XLI", "Materials": "XLB", "Utilities": "XLU",
    "Real Estate": "XLRE", "Communication Services": "XLC",
}

# US Treasury yield-curve points, shortest to longest maturity.
US_YIELD_CURVE = [("3M", "^IRX"), ("5Y", "^FVX"), ("10Y", "^TNX"), ("30Y", "^TYX")]


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------
@st.cache_data(show_spinner=False)
def load_instruments() -> pd.DataFrame:
    """The full multi-asset-class, multi-market instrument table. Run
    `python3 scripts/build_global_universe.py` to regenerate it after
    editing any of the curated lists it's built from."""
    df = pd.read_csv(INSTRUMENTS_PATH)
    df["market_cap_usd_bn"] = pd.to_numeric(df["market_cap_usd_bn"], errors="coerce")
    return df


def asset_classes(df: pd.DataFrame = None) -> list:
    df = df if df is not None else load_instruments()
    present = set(df["asset_class"].unique())
    return [a for a in ASSET_CLASS_ORDER if a in present]


def markets_for(df: pd.DataFrame, asset_class: str = None) -> list:
    sub = df if asset_class is None else df[df["asset_class"] == asset_class]
    present = list(sub["market"].unique())
    ordered = [m for m in EQUITY_MARKET_ORDER if m in present]
    ordered += sorted(m for m in present if m not in ordered)
    return ordered


def filter_instruments(
    df: pd.DataFrame = None,
    asset_classes_sel=None,
    markets_sel=None,
    sectors_sel=None,
) -> pd.DataFrame:
    """Non-UI filtering -- safe to call inside a `st.cache_data`-decorated
    helper (unlike `picker`, which renders widgets)."""
    df = df if df is not None else load_instruments()
    out = df
    if asset_classes_sel:
        out = out[out["asset_class"].isin(asset_classes_sel)]
    if markets_sel:
        out = out[out["market"].isin(markets_sel)]
    if sectors_sel:
        out = out[out["gics_sector"].isin(sectors_sel)]
    return out


def sector_label(asset_class_sel) -> str:
    """The GICS-sector column doubles as a generic category grouping for
    non-equity asset classes -- label the UI control accordingly."""
    if asset_class_sel and set(asset_class_sel) == {"Equity"}:
        return "GICS Sector"
    return "Sector / Category"


def picker(
    key_prefix: str,
    default_asset_classes=("Equity",),
    default_markets=("South Africa",),
    show_sector_filter: bool = True,
    container=None,
) -> pd.DataFrame:
    """Renders Asset Class / Market / Sector-Category multiselect widgets
    and returns the filtered instrument universe. `container` lets a page
    put this in `st.sidebar` or a specific column instead of inline."""
    df = load_instruments()
    box = container if container is not None else st
    ac_opts = asset_classes(df)
    default_ac = [a for a in default_asset_classes if a in ac_opts] or ac_opts
    sel_ac = box.multiselect("Asset Class", ac_opts, default=default_ac, key=f"{key_prefix}_ac")
    sel_ac = sel_ac or ac_opts

    mkt_opts = markets_for(df, None if len(sel_ac) != 1 else sel_ac[0])
    mkt_opts = sorted(set(df[df["asset_class"].isin(sel_ac)]["market"].unique()),
                       key=lambda m: (EQUITY_MARKET_ORDER + [m]).index(m) if m in EQUITY_MARKET_ORDER else 999)
    default_mkt = [m for m in default_markets if m in mkt_opts] or mkt_opts
    sel_mkt = box.multiselect("Market", mkt_opts, default=default_mkt, key=f"{key_prefix}_mkt")
    sel_mkt = sel_mkt or mkt_opts

    filtered = filter_instruments(df, sel_ac, sel_mkt)

    if show_sector_filter:
        sec_opts = sorted(filtered["gics_sector"].dropna().unique())
        sel_sec = box.multiselect(sector_label(sel_ac), sec_opts, default=[], key=f"{key_prefix}_sec")
        if sel_sec:
            filtered = filtered[filtered["gics_sector"].isin(sel_sec)]

    return filtered.reset_index(drop=True)


def cap_display(row) -> str:
    """Human-friendly market-cap string for a universe row."""
    tier = row.get("market_cap_tier", "--")
    cap = row.get("market_cap_usd_bn")
    if tier in (None, "--") and (cap is None or pd.isna(cap)):
        return "--"
    cap_txt = f"${cap:,.1f}bn" if cap is not None and pd.notna(cap) else ""
    return f"{tier} {cap_txt}".strip()

import pandas as pd
import streamlit as st

from src import universe as uni
from src.common import bootstrap
from src.quotes import snapshot_table, style_snapshot
from src.theme import DOWN, UP

bootstrap("World Markets", "🌍")

st.title("🌍 World Markets Overview")
st.caption(
    "A single, cross-asset snapshot: major world equity indices, then a quick read on crypto, "
    "commodities, currencies, and bonds/rates. Every table below is a live Yahoo Finance pull "
    "(most-recent daily bar vs. the prior close) -- click into the dedicated pages in the sidebar "
    "for breadth, charts, and deeper stats on any one of these."
)

instruments = uni.load_instruments()

# --------------------------------------------------------------------------
# Asset-class tiles
# --------------------------------------------------------------------------
tile_cols = st.columns(6)
counts = instruments.groupby("asset_class").size()
tiles = [
    ("🏛️ Equities", "Equity", "10 countries"),
    ("🪙 Crypto", "Crypto", "Top ~40 by category"),
    ("🛢️ Commodities", "Commodity", "Futures + ETF proxies"),
    ("💱 Currencies", "Currency", "Major + EM FX"),
    ("📜 Bonds & Rates", "Bond/Rate", "US Treasury curve + ETFs"),
    ("🏦 Mutual Funds", "Mutual Fund", "Top-rated US funds"),
]
for col, (label, ac, sub) in zip(tile_cols, tiles):
    n = int(counts.get(ac, 0))
    col.markdown(
        f"<div class='jse-card'><b>{label}</b><br>{n} instruments tracked<br>"
        f"<span style='color:#8B93A7'>{sub}</span></div>",
        unsafe_allow_html=True,
    )

st.divider()

# --------------------------------------------------------------------------
# World equity indices table
# --------------------------------------------------------------------------
st.subheader("Major world equity indices")
with st.spinner("Fetching index levels..."):
    idx_df = snapshot_table(uni.WORLD_INDICES, period="5d")

if idx_df.empty:
    st.warning("Couldn't fetch index data right now -- check `python3 scripts/test_data_connection.py`.")
else:
    st.dataframe(style_snapshot(idx_df, UP, DOWN), hide_index=True, width="stretch", height=min(700, 60 + 36 * len(idx_df)))
    up_n = int((idx_df["Chg. %"] > 0).sum())
    st.caption(f"{up_n} of {len(idx_df)} tracked indices up on the day.")

st.divider()

# --------------------------------------------------------------------------
# Per-market equity summary (count of instruments + link-out hint)
# --------------------------------------------------------------------------
st.subheader("Equity markets tracked")
eq = instruments[instruments["asset_class"] == "Equity"]
mkt_summary = (
    eq.groupby("market")
    .agg(Instruments=("symbol", "count"), Sectors=("gics_sector", "nunique"))
    .reindex(uni.EQUITY_MARKET_ORDER)
    .dropna()
    .astype(int)
    .reset_index()
    .rename(columns={"market": "Market"})
)
st.dataframe(mkt_summary, hide_index=True, width="stretch")
st.caption(
    "For sector/industry breadth on any one of these, go to **Market Breadth**; for the US, "
    "**US Sector Breadth** reproduces the classic SPDR-sector-ETF scorecard."
)

st.divider()

# --------------------------------------------------------------------------
# Quick snapshots for the other asset classes
# --------------------------------------------------------------------------
c1, c2 = st.columns(2)
with c1:
    st.subheader("🪙 Crypto (top movers)")
    crypto = instruments[instruments["asset_class"] == "Crypto"]
    with st.spinner("Fetching crypto quotes..."):
        crypto_df = snapshot_table(dict(zip(crypto["name"], crypto["yf_ticker"])), period="5d")
    if crypto_df.empty:
        st.info("No crypto data available right now.")
    else:
        top_movers = crypto_df.reindex(crypto_df["Chg. %"].abs().sort_values(ascending=False).index).head(8)
        st.dataframe(style_snapshot(top_movers, UP, DOWN), hide_index=True, width="stretch")
    st.caption("Full list on the **Crypto** page.")

with c2:
    st.subheader("🛢️💱 Commodities & Currencies (top movers)")
    cc = instruments[instruments["asset_class"].isin(["Commodity", "Currency"])]
    with st.spinner("Fetching commodity/FX quotes..."):
        cc_df = snapshot_table(dict(zip(cc["name"], cc["yf_ticker"])), period="5d")
    if cc_df.empty:
        st.info("No commodity/FX data available right now.")
    else:
        top_movers_cc = cc_df.reindex(cc_df["Chg. %"].abs().sort_values(ascending=False).index).head(8)
        st.dataframe(style_snapshot(top_movers_cc, UP, DOWN), hide_index=True, width="stretch")
    st.caption("Full lists on the **Commodities & Currencies** page.")

st.divider()
st.subheader("📜 US rates snapshot")
yc = dict(uni.US_YIELD_CURVE)
with st.spinner("Fetching Treasury yields..."):
    yc_df = snapshot_table({f"{k} Treasury Yield": v for k, v in yc.items()}, period="5d")
if yc_df.empty:
    st.info("No rates data available right now.")
else:
    st.dataframe(style_snapshot(yc_df, DOWN, UP), hide_index=True, width="stretch")
    st.caption(
        "Note the colour convention is flipped here on purpose: a *rising* yield is shown in the "
        "'down' colour because rising yields usually mean falling bond prices. Full yield curve "
        "and bond ETF performance on the **Bonds & Rates** page."
    )

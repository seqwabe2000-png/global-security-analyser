import streamlit as st

from src import universe as uni
from src.common import bootstrap
from src.quotes import snapshot_table, style_snapshot
from src.theme import DOWN, UP

bootstrap("Commodities & Currencies", "🛢️")

st.title("🛢️💱 Commodities & Currencies")
st.caption(
    "Futures and liquid ETF proxies for precious/industrial metals, energy, and agriculture, plus "
    "major and EM currency pairs and the US Dollar Index -- all via Yahoo Finance."
)

instruments = uni.load_instruments()
commodities = instruments[instruments["asset_class"] == "Commodity"]
currencies = instruments[instruments["asset_class"] == "Currency"]

tab_commod, tab_fx = st.tabs(["🛢️ Commodities", "💱 Currencies"])

with tab_commod:
    group_choice = st.multiselect(
        "Category", sorted(commodities["gics_sector"].unique()), default=[], placeholder="All categories", key="commod_cat"
    )
    scoped = commodities if not group_choice else commodities[commodities["gics_sector"].isin(group_choice)]
    with st.spinner("Fetching commodity quotes..."):
        snap = snapshot_table(dict(zip(scoped["name"], scoped["yf_ticker"])), period="5d")
    if snap.empty:
        st.warning("Couldn't fetch commodity data right now -- check `python3 scripts/test_data_connection.py`.")
    else:
        st.dataframe(
            style_snapshot(snap.sort_values("Chg. %", ascending=False), UP, DOWN),
            hide_index=True, width="stretch", height=min(700, 60 + 36 * len(snap)),
        )
        st.caption(
            "Rows ending `=F` are futures contracts (front-month, continuous); GLD/SLV/USO/UNG/DBC/DBA "
            "are liquid ETF proxies for the same exposure if you'd rather track a fund than a future."
        )

with tab_fx:
    fx_group = st.radio("Show", ["All", "Major FX", "EM FX", "Dollar Index"], horizontal=True, key="fx_group")
    if fx_group == "All":
        scoped_fx = currencies
    else:
        scoped_fx = currencies[currencies["gics_sector"] == fx_group]
    with st.spinner("Fetching FX quotes..."):
        snap_fx = snapshot_table(dict(zip(scoped_fx["name"], scoped_fx["yf_ticker"])), period="5d")
    if snap_fx.empty:
        st.warning("Couldn't fetch FX data right now -- check `python3 scripts/test_data_connection.py`.")
    else:
        st.dataframe(
            style_snapshot(snap_fx.sort_values("Chg. %", ascending=False), UP, DOWN),
            hide_index=True, width="stretch", height=min(700, 60 + 36 * len(snap_fx)),
        )
        st.caption(
            "Pairs are quoted `BASE/QUOTE` the way Yahoo Finance labels them (e.g. EURUSD=X is euros "
            "per US dollar -- a rising value means the euro is strengthening against the dollar)."
        )

st.caption(
    "For charts, distribution of returns, ATR%, rolling vol/beta, relative performance, and pairs "
    "analysis on any individual commodity or FX pair, use those pages and pick "
    "**Asset Class = Commodity / Currency** in the universe picker at the top."
)

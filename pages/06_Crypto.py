import pandas as pd
import plotly.express as px
import streamlit as st

from src import data, indicators
from src import universe as uni
from src.common import bootstrap
from src.quotes import snapshot_table, style_snapshot
from src.theme import DOWN, UP

bootstrap("Crypto", "🪙")

st.title("🪙 Crypto")
st.caption(
    "Top ~40 cryptocurrencies by category, via Yahoo Finance `-USD` tickers. 'Sector' here is the "
    "narrative/category a coin is best known for (Layer 1, DeFi, Meme, etc.), not a financial sector -- "
    "used the same way GICS sectors are used for equities, so the same breadth/screener logic applies."
)

instruments = uni.load_instruments()
crypto = instruments[instruments["asset_class"] == "Crypto"]

st.subheader("Live snapshot")
with st.spinner("Fetching crypto quotes..."):
    snap = snapshot_table(dict(zip(crypto["name"] + " (" + crypto["symbol"] + ")", crypto["yf_ticker"])), period="5d")

if snap.empty:
    st.warning("Couldn't fetch crypto data right now -- check `python3 scripts/test_data_connection.py`.")
else:
    sort_choice = st.radio("Sort by", ["Chg. %", "Name"], horizontal=True, key="crypto_sort")
    snap_sorted = snap.sort_values("Chg. %", ascending=False) if sort_choice == "Chg. %" else snap.sort_values("Name")
    st.dataframe(style_snapshot(snap_sorted, UP, DOWN), hide_index=True, width="stretch", height=min(900, 60 + 36 * len(snap)))
    up_n = int((snap["Chg. %"] > 0).sum())
    st.caption(f"{up_n} of {len(snap)} tracked coins up on the day.")

st.divider()

# --------------------------------------------------------------------------
# Breadth by category
# --------------------------------------------------------------------------
st.subheader("Breadth by category")
sma_window = st.selectbox("SMA window", [20, 50, 100, 200], index=1, key="crypto_sma")
run = st.button("Run crypto breadth scan", type="primary")

if run:
    hist = data.get_history_bulk(crypto["yf_ticker"].tolist(), period="18mo", interval="1d")
    rows = []
    for _, r in crypto.iterrows():
        df = hist.get(r["yf_ticker"])
        if df is None or df.empty or len(df) < sma_window:
            continue
        above = indicators.pct_above_sma(df, sma_window)
        if above is None:
            continue
        rows.append({"Symbol": r["symbol"], "Category": r["gics_sector"], f"Above {sma_window}-SMA": above})
    st.session_state["crypto_breadth_df"] = pd.DataFrame(rows)
    st.session_state["crypto_breadth_sma_used"] = sma_window

if "crypto_breadth_df" in st.session_state:
    bdf = st.session_state["crypto_breadth_df"]
    sma_used = st.session_state["crypto_breadth_sma_used"]
    col = f"Above {sma_used}-SMA"
    if bdf.empty:
        st.warning("No breadth data could be computed.")
    else:
        total, above_count = len(bdf), int(bdf[col].sum())
        m1, m2, m3 = st.columns(3)
        m1.metric("Coins scanned", total)
        m2.metric(f"Above {sma_used}-SMA", f"{above_count} ({above_count / total * 100:.1f}%)")
        m3.metric(f"Below {sma_used}-SMA", f"{total - above_count} ({(total - above_count) / total * 100:.1f}%)")

        cat_breadth = (
            bdf.groupby("Category")[col].agg(Above="sum", Total="count")
            .assign(Pct=lambda d: (d["Above"] / d["Total"] * 100).round(1))
            .sort_values("Pct", ascending=False).reset_index()
        )
        fig = px.bar(
            cat_breadth, x="Pct", y="Category", orientation="h",
            text=cat_breadth.apply(lambda r: f"{r['Above']}/{r['Total']} ({r['Pct']}%)", axis=1),
            color="Pct", color_continuous_scale=[DOWN, "#8B93A7", UP], range_color=[0, 100],
        )
        fig.update_layout(height=420, coloraxis_showscale=False, xaxis_title=f"% above {sma_used}-SMA", yaxis_title="")
        st.plotly_chart(fig, width="stretch")
else:
    st.info("Click **Run crypto breadth scan** to compute breadth across tracked coins.")

st.caption(
    "For candlestick charts, distribution of returns, ATR%, rolling vol/beta, relative performance and "
    "pairs analysis on any individual coin, use those pages and pick **Asset Class = Crypto** in the "
    "universe picker at the top."
)

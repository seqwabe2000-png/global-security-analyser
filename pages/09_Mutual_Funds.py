import pandas as pd
import plotly.express as px
import streamlit as st

from src import data, indicators
from src import universe as uni
from src.common import bootstrap
from src.quotes import snapshot_table, style_snapshot
from src.theme import DOWN, UP

bootstrap("Mutual Funds", "🏦")

st.title("🏦 Mutual Funds")
st.caption(
    "Well-known US mutual funds, sourced from Yahoo Finance's own fund screener when this app is run "
    "with internet access (several of its predefined fund screens -- top-rated, large/mid-cap growth, "
    "conservative foreign, high-yield bond, etc. -- merged and deduped), falling back to a small curated "
    "list of widely-held funds otherwise. 'Category' here is the fund's own Morningstar-style category "
    "(Large Blend, Foreign Large Blend, Intermediate Bond, ...), used the same way GICS sectors are "
    "used for equities."
)

instruments = uni.load_instruments()
funds = instruments[instruments["asset_class"] == "Mutual Fund"]

st.subheader("Live snapshot")
with st.spinner("Fetching fund quotes..."):
    snap = snapshot_table(dict(zip(funds["name"] + " (" + funds["symbol"] + ")", funds["yf_ticker"])), period="5d")

if snap.empty:
    st.warning("Couldn't fetch fund data right now -- check `python3 scripts/test_data_connection.py`.")
else:
    st.dataframe(
        style_snapshot(snap.sort_values("Chg. %", ascending=False), UP, DOWN),
        hide_index=True, width="stretch", height=min(700, 60 + 36 * len(snap)),
    )
    up_n = int((snap["Chg. %"] > 0).sum())
    st.caption(f"{up_n} of {len(snap)} tracked funds up on the day. Mutual funds only price once per day (NAV), so intraday Open/High/Low can look flat -- that's expected, not a data error.")

st.divider()

st.subheader("Breadth by category")
sma_window = st.selectbox("SMA window", [20, 50, 100, 200], index=1, key="fund_sma")
run = st.button("Run fund breadth scan", type="primary")

if run:
    hist = data.get_history_bulk(funds["yf_ticker"].tolist(), period="18mo", interval="1d")
    rows = []
    for _, r in funds.iterrows():
        df = hist.get(r["yf_ticker"])
        if df is None or df.empty or len(df) < sma_window:
            continue
        above = indicators.pct_above_sma(df, sma_window)
        if above is None:
            continue
        rows.append({"Symbol": r["symbol"], "Category": r["gics_sector"], f"Above {sma_window}-SMA": above})
    st.session_state["fund_breadth_df"] = pd.DataFrame(rows)
    st.session_state["fund_breadth_sma_used"] = sma_window

if "fund_breadth_df" in st.session_state:
    bdf = st.session_state["fund_breadth_df"]
    sma_used = st.session_state["fund_breadth_sma_used"]
    col = f"Above {sma_used}-SMA"
    if bdf.empty:
        st.warning("No breadth data could be computed.")
    else:
        total, above_count = len(bdf), int(bdf[col].sum())
        m1, m2, m3 = st.columns(3)
        m1.metric("Funds scanned", total)
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
    st.info("Click **Run fund breadth scan** to compute breadth across tracked funds.")

st.caption(
    "For charts, distribution of returns, rolling vol/beta, relative performance, and pairs analysis on "
    "any individual fund, use those pages and pick **Asset Class = Mutual Fund** in the universe picker."
)

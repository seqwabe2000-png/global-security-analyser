import pandas as pd
import plotly.express as px
import streamlit as st

from src import data, indicators
from src import universe as uni
from src.common import bootstrap
from src.quotes import snapshot_table, style_snapshot
from src.theme import DOWN, UP

bootstrap("US Sector Breadth", "🇺🇸")

st.title("🇺🇸 US Sector Breadth")
st.caption(
    "The 11 SPDR Select Sector ETFs (real, tradable instruments) plus the broad-market ETFs, exactly "
    "like the sector scorecards you'd see on a market-data terminal -- paired with **breadth**: what "
    "share of that sector's actual constituent stocks (from this app's curated ~120-name US universe) "
    "are trading above a chosen moving average right now."
)

instruments = uni.load_instruments()
us_equities = instruments[(instruments["asset_class"] == "Equity") & (instruments["market"] == "United States")]

# --------------------------------------------------------------------------
# 1. Sector ETF scorecard (matches the reference screenshot table shape)
# --------------------------------------------------------------------------
st.subheader("Sector & broad-market ETFs")
all_etfs = {**uni.US_BROAD_ETFS, **uni.US_SECTOR_ETFS}
with st.spinner("Fetching ETF quotes..."):
    etf_df = snapshot_table(all_etfs, period="5d")

if etf_df.empty:
    st.warning("Couldn't fetch ETF data right now -- check `python3 scripts/test_data_connection.py`.")
else:
    st.dataframe(
        style_snapshot(etf_df.sort_values("Chg. %", ascending=False), UP, DOWN),
        hide_index=True, width="stretch", height=min(700, 60 + 36 * len(etf_df)),
    )
    up_n = int((etf_df["Chg. %"] > 0).sum())
    total_n = len(etf_df)
    st.caption(f"{up_n} of {total_n} tracked ETFs up on the day.")

st.divider()

# --------------------------------------------------------------------------
# 2. Sector breadth -- % of each sector's constituent stocks above SMA
# --------------------------------------------------------------------------
st.subheader("Sector breadth (constructed from constituent stocks)")
sma_window = st.selectbox("SMA window", [20, 50, 100, 200], index=3, key="us_breadth_sma")
run = st.button("Run US sector breadth scan", type="primary")

if run:
    progress = st.progress(0.0, text="Fetching price data...")

    def _cb(done, total):
        progress.progress(done / total, text=f"Fetching price data... chunk {done}/{total}")

    hist = data.get_history_bulk(us_equities["yf_ticker"].tolist(), period="18mo", interval="1d", progress_cb=_cb)
    progress.empty()

    rows = []
    for _, r in us_equities.iterrows():
        df = hist.get(r["yf_ticker"])
        if df is None or df.empty or len(df) < sma_window:
            continue
        above = indicators.pct_above_sma(df, sma_window)
        if above is None:
            continue
        rows.append({"Symbol": r["symbol"], "Sector": r["gics_sector"], f"Above {sma_window}-SMA": above})

    st.session_state["us_breadth_df"] = pd.DataFrame(rows)
    st.session_state["us_breadth_sma_used"] = sma_window

if "us_breadth_df" not in st.session_state:
    st.info("Click **Run US sector breadth scan** to compute breadth for the ~120-stock US universe.")
    st.stop()

breadth_df = st.session_state["us_breadth_df"]
sma_used = st.session_state["us_breadth_sma_used"]
col_name = f"Above {sma_used}-SMA"

sector_breadth = (
    breadth_df.groupby("Sector")[col_name]
    .agg(Above="sum", Total="count")
    .assign(Pct=lambda d: (d["Above"] / d["Total"] * 100).round(1))
    .reset_index()
)
sector_breadth["SPDR ETF"] = sector_breadth["Sector"].map(uni.US_SECTOR_TO_ETF).fillna("--")
sector_breadth = sector_breadth.sort_values("Pct", ascending=False)

fig = px.bar(
    sector_breadth, x="Pct", y="Sector", orientation="h",
    text=sector_breadth.apply(lambda r: f"{r['Above']}/{r['Total']} ({r['Pct']}%) · {r['SPDR ETF']}", axis=1),
    color="Pct", color_continuous_scale=[DOWN, "#8B93A7", UP], range_color=[0, 100],
)
fig.update_layout(height=460, coloraxis_showscale=False, xaxis_title=f"% above {sma_used}-SMA", yaxis_title="", margin=dict(t=10))
st.plotly_chart(fig, width="stretch")

total = len(breadth_df)
above_count = int(breadth_df[col_name].sum())
m1, m2, m3 = st.columns(3)
m1.metric("Stocks scanned", total)
m2.metric(f"Above {sma_used}-SMA", f"{above_count} ({above_count / total * 100:.1f}%)" if total else "—")
m3.metric(f"Below {sma_used}-SMA", f"{total - above_count} ({(total - above_count) / total * 100:.1f}%)" if total else "—")

with st.expander("Show underlying stock-level data"):
    st.dataframe(breadth_df.sort_values(col_name, ascending=False), hide_index=True, width="stretch")

st.caption(
    "Curation note: this app's US equity universe is a hand-curated ~120-name representative set spanning "
    "all 11 GICS sectors (see README), not the full S&P 500 -- breadth % is relative to that set, not the "
    "index. The SPDR ETF prices above are the real, official instrument for each sector; only the breadth "
    "percentage is 'constructed' from the constituent list."
)

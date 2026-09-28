import plotly.graph_objects as go
import streamlit as st

from src import data
from src import universe as uni
from src.common import bootstrap
from src.quotes import snapshot_table, style_snapshot
from src.theme import ACCENT, ACCENT_2, DOWN, MUTED, UP

bootstrap("Bonds & Rates", "📜")

st.title("📜 Bonds & Rates")
st.caption(
    "US Treasury yield curve (via Yahoo's `^IRX`/`^FVX`/`^TNX`/`^TYX` yield tickers) plus liquid bond "
    "ETFs across the maturity/credit spectrum. There's no free, broad live feed for other countries' "
    "sovereign yield curves, so this page is US-focused; international bond *ETF* exposure (BNDX, EMB) "
    "is still included below."
)

instruments = uni.load_instruments()
bonds = instruments[instruments["asset_class"] == "Bond/Rate"]

# --------------------------------------------------------------------------
# Yield curve
# --------------------------------------------------------------------------
st.subheader("US Treasury yield curve")
curve_tickers = dict(uni.US_YIELD_CURVE)
with st.spinner("Fetching yields..."):
    curve_hist = data.get_history_bulk(list(curve_tickers.values()), period="5y", interval="1d")

latest_yields = {}
for label, ticker in curve_tickers.items():
    df = curve_hist.get(ticker)
    if df is not None and not df.empty:
        latest_yields[label] = df["Close"].iloc[-1]

if not latest_yields:
    st.warning("Couldn't fetch Treasury yield data right now -- check `python3 scripts/test_data_connection.py`.")
else:
    order = [lbl for lbl, _ in uni.US_YIELD_CURVE if lbl in latest_yields]
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=order, y=[latest_yields[l] for l in order], mode="lines+markers",
        line=dict(color=ACCENT, width=2.5), marker=dict(size=9), name="Latest curve",
    ))
    fig.update_layout(height=380, yaxis_title="Yield (%)", xaxis_title="Maturity", margin=dict(t=10))
    st.plotly_chart(fig, width="stretch")

    inverted = latest_yields.get("3M", 0) > latest_yields.get("10Y", 0)
    if inverted:
        st.warning("The curve is currently **inverted** (3M yield above 10Y yield) -- historically a widely watched recession signal.")
    else:
        st.caption("Curve is currently upward-sloping (not inverted) on this reading.")

st.divider()

# --------------------------------------------------------------------------
# 10Y yield over time
# --------------------------------------------------------------------------
st.subheader("10-Year Treasury Yield, historical")
period = st.selectbox("History", ["1y", "3y", "5y", "10y", "max"], index=2, key="tnx_period")
tnx = data.get_history("^TNX", period=period, interval="1d")
if tnx.empty:
    st.info("No 10-year yield history available.")
else:
    fig2 = go.Figure()
    fig2.add_trace(go.Scatter(x=tnx.index, y=tnx["Close"], mode="lines", line=dict(color=ACCENT_2, width=1.6)))
    fig2.update_layout(height=350, yaxis_title="Yield (%)", margin=dict(t=10))
    st.plotly_chart(fig2, width="stretch")

st.divider()

# --------------------------------------------------------------------------
# Bond ETF performance table
# --------------------------------------------------------------------------
st.subheader("Bond ETF performance")
etfs = bonds[bonds["industry"].str.contains("ETF", case=False, na=False)]
with st.spinner("Fetching bond ETF quotes..."):
    snap = snapshot_table(dict(zip(etfs["name"] + " (" + etfs["symbol"] + ")", etfs["yf_ticker"])), period="5d")
if snap.empty:
    st.warning("Couldn't fetch bond ETF data right now.")
else:
    st.dataframe(
        style_snapshot(snap.sort_values("Chg. %", ascending=False), UP, DOWN),
        hide_index=True, width="stretch", height=min(700, 60 + 36 * len(snap)),
    )
    st.caption(
        "Remember bond ETF prices move **inversely** to yields -- TLT (20+yr) falling usually means "
        "long yields rising, not a credit problem with the fund itself."
    )

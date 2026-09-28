import plotly.graph_objects as go
import streamlit as st

from src import data, indicators
from src import universe as uni
from src.common import bootstrap
from src.theme import ACCENT, ACCENT_2, MUTED

bootstrap("ATR %", "📐")

st.title("📐 Average True Range % (ATRP)")
st.caption(
    "Reproduces ATRP_Template.xlsx: True Range % = MAX(High−Low, |High−PrevClose|, |PrevClose−Low|) ÷ Open, "
    "averaged over the same trading-horizon windows as the template (1 week through 50 years). Works for "
    "any instrument: equities, crypto, commodities, currencies, or bonds/rates."
)

universe = uni.picker("atrp", default_asset_classes=["Equity"], default_markets=["South Africa"], show_sector_filter=False)

c1, c2, c3, c4 = st.columns([1.3, 2, 1, 1])
with c1:
    timeframe = st.selectbox("Timeframe", ["Daily", "Weekly", "Monthly", "Quarterly"], index=0)
with c2:
    sector_filter = st.selectbox(uni.sector_label(universe["asset_class"].unique().tolist()), ["All"] + sorted(universe["gics_sector"].unique()))
    stock_universe = universe if sector_filter == "All" else universe[universe["gics_sector"] == sector_filter]
with c3:
    label_to_ticker = {f"{r['symbol']} — {r['name']}": r["yf_ticker"] for _, r in stock_universe.iterrows()}
    if not label_to_ticker:
        st.warning("No instruments in this selection.")
        st.stop()
    choice = st.selectbox("Instrument", options=sorted(label_to_ticker.keys()))
    ticker = label_to_ticker[choice]
with c4:
    history_period = st.selectbox("History", ["2y", "5y", "10y", "max"], index=2)

raw = data.get_history(ticker, period=history_period, interval="1d")
if raw.empty:
    st.error(f"No price data available for {ticker}.")
    st.stop()

df = raw if timeframe == "Daily" else data.resample_ohlc(raw, {"Weekly": "W", "Monthly": "M", "Quarterly": "Q"}[timeframe])

trp = indicators.true_range_pct(df).dropna()
if trp.empty:
    st.error("Not enough data to compute True Range %.")
    st.stop()

horizons = indicators.ATRP_HORIZONS[timeframe]
atrp_table = indicators.average_true_range_pct(df, horizons)

one_year_row = atrp_table[atrp_table["Horizon"] == "1 Year"]
if one_year_row.empty or one_year_row["Avg True Range %"].isna().all():
    # fall back to whichever horizon has the most data (e.g. Quarterly timeframe has no "1 Year" row)
    fallback = atrp_table.dropna(subset=["Avg True Range %"])
    headline_label = fallback.iloc[0]["Horizon"] if not fallback.empty else "—"
    headline_val = fallback.iloc[0]["Avg True Range %"] if not fallback.empty else None
else:
    headline_label = "1 Year"
    headline_val = one_year_row["Avg True Range %"].iloc[0]

m1, m2, m3 = st.columns(3)
m1.metric("Latest True Range %", f"{trp.iloc[-1]:.2%}")
m2.metric(f"{headline_label} avg True Range %", f"{headline_val:.2%}" if headline_val == headline_val and headline_val is not None else "—")
m3.metric(f"{timeframe} bars used", len(df))

st.divider()

col1, col2 = st.columns([1.1, 1])
with col1:
    st.subheader("Average True Range % by horizon")
    display_table = atrp_table.copy()
    display_table["Avg True Range %"] = display_table["Avg True Range %"].map(
        lambda x: f"{x:.3%}" if x == x else "—"  # NaN check
    )
    st.dataframe(display_table, hide_index=True, width="stretch")

    fig = go.Figure()
    plot_df = atrp_table.dropna(subset=["Avg True Range %"])
    fig.add_trace(
        go.Bar(x=plot_df["Horizon"], y=plot_df["Avg True Range %"], marker_color=ACCENT, name="Avg TR%")
    )
    fig.update_layout(height=380, yaxis_tickformat=".2%", yaxis_title="Avg True Range %", xaxis_title="")
    st.plotly_chart(fig, width="stretch")

with col2:
    st.subheader(f"{timeframe} True Range % over time")
    recent = trp.tail(min(len(trp), 500))
    fig2 = go.Figure()
    fig2.add_trace(go.Scatter(x=recent.index, y=recent, mode="lines", line=dict(color=ACCENT_2, width=1.2), name="TR%"))
    fig2.add_hline(y=trp.mean(), line_dash="dot", line_color=MUTED, annotation_text="Full-history mean")
    fig2.update_layout(height=380, yaxis_tickformat=".2%", yaxis_title="True Range %", xaxis_title="")
    st.plotly_chart(fig2, width="stretch")

st.caption(
    "\"Periods Available\" below the requested horizon means there isn't enough history to fill that "
    "window yet -- the average is computed over whatever is available instead of blowing up."
)

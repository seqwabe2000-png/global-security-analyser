import numpy as np
import plotly.graph_objects as go
import streamlit as st

from src import data, indicators
from src import universe as uni
from src.common import bootstrap
from src.theme import ACCENT, ACCENT_2, DOWN, MUTED, UP
from src.ui import percentile_grid_html

bootstrap("Distribution of Returns", "📉")

st.title("📉 Distribution of Returns")
st.caption(
    "Reproduces the stats in DoR_Template.xlsx -- Close-to-Close, High-to-Low, Open-to-Close, and "
    "Close-to-Open (overnight) return distributions, with the same descriptive-statistics block and "
    "histogram bins. Works for any instrument: equities, crypto, commodities, currencies, or bonds/rates."
)

universe = uni.picker("dor", default_asset_classes=["Equity"], default_markets=["South Africa"], show_sector_filter=False)

# --------------------------------------------------------------------------
# Filters
# --------------------------------------------------------------------------
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

return_type = st.radio(
    "Return series",
    [
        "C-C Return (Close-to-Close)",
        "H-L Return (High-to-Low)",
        "O-C Return (Open-to-Close)",
        "C-O Return (Close-to-Open, overnight)",
    ],
    horizontal=True,
)
return_col = {
    "C-C": "C-C Return",
    "H-L": "H-L Return",
    "O-C": "O-C Return",
    "C-O": "C-O Return",
}[return_type.split(" ")[0]]

# --------------------------------------------------------------------------
# Data
# --------------------------------------------------------------------------
raw = data.get_history(ticker, period=history_period, interval="1d")
if raw.empty:
    st.error(f"No price data available for {ticker}.")
    st.stop()

df = raw if timeframe == "Daily" else data.resample_ohlc(raw, {"Weekly": "W", "Monthly": "M", "Quarterly": "Q"}[timeframe])
if len(df) < 10:
    st.warning(f"Only {len(df)} {timeframe.lower()} bars available for {choice} -- stats below will be unreliable.")

returns = indicators.compute_returns(df)
series = returns[return_col]

if series.dropna().empty:
    st.error("Not enough data to compute a return distribution.")
    st.stop()

periods_per_year = indicators.PERIODS_PER_YEAR[timeframe]
stats = indicators.descriptive_stats(series, periods_per_year)
bins = indicators.distribution_bins(series)

# --------------------------------------------------------------------------
# Headline metrics
# --------------------------------------------------------------------------
m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Mean", f"{stats['Mean']:.3%}")
m2.metric("Std Dev", f"{stats['Standard Deviation']:.3%}")
m3.metric("Skewness", f"{stats['Skewness']:.2f}")
m4.metric("Kurtosis", f"{stats['Kurtosis']:.2f}")
m5.metric("Annualised Mean / Std", f"{stats['Annualised Mean']:.1%} / {stats['Annualised Std Dev']:.1%}")

st.divider()

col_chart, col_stats = st.columns([2, 1])

with col_chart:
    st.subheader(f"{choice.split(' — ')[0]} · {timeframe} {return_type.split(' (')[0]} distribution")
    colors = []
    for label in bins["Range"]:
        colors.append(DOWN if label.startswith("Less") else (UP if label.startswith("Greater") else ACCENT_2))
    fig = go.Figure()
    fig.add_trace(go.Bar(x=bins["Range"], y=bins["Frequency"], marker_color=colors, name="Frequency"))
    fig.update_layout(
        height=440,
        xaxis_title="Return bucket (mean ± k·σ edges)",
        yaxis_title="Frequency (# of periods)",
        xaxis_tickangle=-40,
        showlegend=False,
    )
    st.plotly_chart(fig, width="stretch")

    st.markdown("**Cumulative probability**")
    fig2 = go.Figure()
    fig2.add_trace(
        go.Scatter(x=bins["Range"], y=bins["Cumulative Probability"], mode="lines+markers", line=dict(color=ACCENT))
    )
    fig2.update_layout(height=280, yaxis_tickformat=".0%", xaxis_tickangle=-40, xaxis_title="", yaxis_title="Cumulative probability")
    st.plotly_chart(fig2, width="stretch")

with col_stats:
    st.subheader("Descriptive statistics")
    stat_order = [
        "Mean", "Standard Error", "Median", "Mode", "Standard Deviation", "Sample Variance",
        "Kurtosis", "Skewness", "Range", "Minimum", "Maximum", "Sum", "Count",
        "Annualised Mean", "Annualised Std Dev",
    ]
    pct_stats = {"Mean", "Standard Error", "Median", "Mode", "Standard Deviation", "Sample Variance",
                 "Range", "Minimum", "Maximum", "Sum", "Annualised Mean", "Annualised Std Dev"}
    rows = []
    for k in stat_order:
        v = stats.get(k)
        if v is None or (isinstance(v, float) and np.isnan(v)):
            rows.append((k, "—"))
        elif k == "Count":
            rows.append((k, f"{int(v)}"))
        elif k in pct_stats:
            rows.append((k, f"{v:.3%}"))
        else:
            rows.append((k, f"{v:.3f}"))
    st.table({"Statistic": [r[0] for r in rows], "Value": [r[1] for r in rows]})

st.subheader("Bin table")
display_bins = bins.copy()
display_bins["Probability"] = display_bins["Probability"].map(lambda x: f"{x:.2%}")
display_bins["Cumulative Probability"] = display_bins["Cumulative Probability"].map(lambda x: f"{x:.2%}")
st.dataframe(display_bins, hide_index=True, width="stretch")

# --------------------------------------------------------------------------
# Percentile table -- "what return level corresponds to the Nth percentile
# of this stock's historical return distribution" (used later by the Stops
# & Targets page's DoR method for percentile-based stop/target levels).
# --------------------------------------------------------------------------
st.subheader("Percentile table")
pct_table = indicators.percentile_table(series)
st.markdown(percentile_grid_html(pct_table), unsafe_allow_html=True)
st.caption(
    "E.g. the 5% percentile is the return level that only the worst 5% of historical periods fell "
    "below -- a downside-risk read that doesn't assume a normal distribution."
)

# --------------------------------------------------------------------------
# Empirical distribution -- positive/negative/zero buckets and actual-vs-
# normal standard-deviation band counts (matches DoR_Template.xlsx).
# --------------------------------------------------------------------------
st.subheader("Empirical distribution")
ed = indicators.empirical_distribution(series)

ed_c1, ed_c2 = st.columns(2)
with ed_c1:
    st.markdown("**Positive / negative / zero data points**")
    buckets_display = ed["buckets"].copy()
    if not buckets_display.empty:
        buckets_display["Average Returns"] = buckets_display["Average Returns"].map(lambda x: f"{x:.2%}")
        buckets_display["Frequency %"] = buckets_display["Frequency %"].map(lambda x: f"{x:.2f}%")
        buckets_display["Frequency Adjusted Return"] = buckets_display["Frequency Adjusted Return"].map(lambda x: f"{x:.2%}")
    st.dataframe(buckets_display, hide_index=True, width="stretch")
with ed_c2:
    st.markdown("**Actual vs. theoretical normal distribution**")
    bands_display = ed["bands"].copy()
    if not bands_display.empty:
        bands_display["Std Dev"] = bands_display["Std Dev"].map(lambda k: f"±{k}σ")
        bands_display["Upper Bound"] = bands_display["Upper Bound"].map(lambda x: f"{x:.2%}")
        bands_display["Lower Bound"] = bands_display["Lower Bound"].map(lambda x: f"{x:.2%}")
        bands_display["Actual % Count"] = bands_display["Actual % Count"].map(lambda x: f"{x:.2f}%")
        bands_display["Normal % Count"] = bands_display["Normal % Count"].map(lambda x: f"{x:.2f}%")
    st.dataframe(bands_display, hide_index=True, width="stretch")
st.caption(
    "If \"Actual %\" runs well ahead of \"Normal %\" at ±1σ (fatter middle) and/or behind at ±3σ "
    "(fatter tails), this stock's returns deviate from a normal distribution -- common for real "
    "equity return series."
)

# --------------------------------------------------------------------------
# Returns over time, with mean ± 1/2/3 std-dev reference lines (matches the
# DoR_Template.xlsx returns chart under each frequency's bin table)
# --------------------------------------------------------------------------
st.subheader(f"{return_col} over time")
plot_series = series.dropna()
mean, std = stats["Mean"], stats["Standard Deviation"]
bar_colors = [UP if v >= 0 else DOWN for v in plot_series]

fig3 = go.Figure()
fig3.add_trace(go.Bar(x=plot_series.index, y=plot_series.values, marker_color=bar_colors, marker_line_width=0, name=return_col))

sigma_style = {1: ("solid", "#8B93A7"), 2: ("dash", "#FFB020"), 3: ("dot", "#EF5350")}
for k, (dash, color) in sigma_style.items():
    for sign, sign_label in ((1, "+"), (-1, "-")):
        if std and not np.isnan(std):
            fig3.add_hline(
                y=mean + sign * k * std,
                line_dash=dash,
                line_color=color,
                opacity=0.85,
                annotation_text=f"{sign_label}{k}σ",
                annotation_position="right",
                annotation_font_color=color,
            )
if not np.isnan(mean):
    fig3.add_hline(y=mean, line_color=MUTED, opacity=0.6, annotation_text="Mean", annotation_position="right")

fig3.update_layout(
    height=400,
    yaxis_title=f"{return_col} (%)",
    yaxis_tickformat=".2%",
    xaxis_title="",
    showlegend=False,
    margin=dict(r=60),
)
st.plotly_chart(fig3, width="stretch")
st.caption(
    "Dashed/dotted lines mark mean ± 1σ, ±2σ, ±3σ -- the same standard-deviation "
    "bands used to build the bin edges above."
)

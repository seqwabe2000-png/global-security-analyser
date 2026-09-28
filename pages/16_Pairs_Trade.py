import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from dateutil.relativedelta import relativedelta
from plotly.subplots import make_subplots

from src import data, indicators, pairs
from src import relative_performance as rp
from src import universe as uni
from src.common import bootstrap
from src.theme import ACCENT, ACCENT_2, DOWN, MUTED, UP

bootstrap("Pairs Trade", "⚖️")

st.title("⚖️ Pairs Trade")
st.caption(
    "Pick two instruments to analyse as a pairs-trade candidate -- any two, even across asset classes "
    "(e.g. gold vs. a gold miner, or Bitcoin vs. a tech stock): normalized performance overlay, price "
    "ratio (spread), rolling correlation, rolling z-score of the spread, and a cointegration + "
    "mean-reversion half-life check. These are standard statistical diagnostics, not a signal to "
    "trade on by themselves -- not investment advice."
)

universe = uni.picker("pairs", default_asset_classes=["Equity"], default_markets=["South Africa"], show_sector_filter=False)
label_to_row = {f"{r['symbol']} — {r['name']}": r for _, r in universe.iterrows()}
labels = sorted(label_to_row.keys())

c1, c2 = st.columns(2)
with c1:
    label_a = st.selectbox("Instrument A", labels, index=0, key="pt_a")
with c2:
    default_b_idx = 1 if len(labels) > 1 else 0
    label_b = st.selectbox("Instrument B", labels, index=default_b_idx, key="pt_b")

row_a, row_b = label_to_row[label_a], label_to_row[label_b]

extra_labels = st.multiselect(
    "Also show on the overlay chart (not included in the spread/correlation/cointegration stats below)",
    [l for l in labels if l not in (label_a, label_b)] + list(rp.BROAD_INDEX_CANDIDATES.keys()),
    key="pt_extra",
)

# --------------------------------------------------------------------------
# Frequency + rolling window + chart timeframe
# --------------------------------------------------------------------------
PAIRS_ROLL_WINDOWS = {
    "Daily": [30, 60, 90, 120, 252],
    "Weekly": [4, 8, 13, 26, 52],
    "Monthly": [3, 6, 12, 24],
}
DEFAULT_WINDOW_IDX = {"Daily": 1, "Weekly": 2, "Monthly": 1}

c3, c4, c5 = st.columns([1, 1, 2])
with c3:
    frequency = st.selectbox("Frequency", ["Daily", "Weekly", "Monthly"], index=0, key="pt_freq")
with c4:
    window_options = PAIRS_ROLL_WINDOWS[frequency]
    window = st.selectbox(
        f"Rolling window ({frequency.lower()} bars)",
        window_options,
        index=DEFAULT_WINDOW_IDX[frequency],
        key=f"pt_window_{frequency}",
    )
with c5:
    timeframe = st.radio(
        "Chart timeframe", rp.TIMEFRAMES, index=rp.TIMEFRAMES.index("1Y"), horizontal=True, key="pt_tf"
    )

if row_a["yf_ticker"] == row_b["yf_ticker"]:
    st.warning("Pick two different stocks to compare.")
    st.stop()


def _hist_lookup(tickers):
    return data.get_history_bulk(tickers, period="max", interval="1d")


with st.spinner("Fetching price history..."):
    hist = _hist_lookup([row_a["yf_ticker"], row_b["yf_ticker"]])
    df_a, df_b = hist.get(row_a["yf_ticker"]), hist.get(row_b["yf_ticker"])

if df_a is None or df_a.empty or df_b is None or df_b.empty:
    st.error("Couldn't get price data for one or both stocks -- check `python3 scripts/test_data_connection.py`.")
    st.stop()

resample_freq = {"Daily": None, "Weekly": "W", "Monthly": "M"}[frequency]
if resample_freq is not None:
    df_a = data.resample_ohlc(df_a, resample_freq)
    df_b = data.resample_ohlc(df_b, resample_freq)

close_a = df_a["Adj Close"] if "Adj Close" in df_a.columns else df_a["Close"]
close_b = df_b["Adj Close"] if "Adj Close" in df_b.columns else df_b["Close"]

# --------------------------------------------------------------------------
# Volatility & correlation/beta summary -- a clearer, table-first view of
# how the two stocks relate, modeled on the Rolling Stats & Beta page.
# --------------------------------------------------------------------------
st.subheader("Volatility & correlation/beta summary")

sliced_a_for_vol = rp.slice_to_timeframe(close_a, timeframe)
sliced_b_for_vol = rp.slice_to_timeframe(close_b, timeframe)
periods_per_year = indicators.PERIODS_PER_YEAR.get(frequency, 252)
vol_a = sliced_a_for_vol.pct_change().dropna().std() * np.sqrt(periods_per_year)
vol_b = sliced_b_for_vol.pct_change().dropna().std() * np.sqrt(periods_per_year)

aligned_full = pd.concat({"a": close_a.pct_change(), "b": close_b.pct_change()}, axis=1).dropna()
whole_corr = aligned_full["a"].corr(aligned_full["b"]) if len(aligned_full) > 2 else np.nan
whole_beta = (
    aligned_full["a"].cov(aligned_full["b"]) / aligned_full["a"].var()
    if len(aligned_full) > 2 and aligned_full["a"].var()
    else np.nan
)

vm1, vm2, vm3, vm4 = st.columns(4)
vm1.metric(f"{row_a['symbol']} annualised vol", f"{vol_a:.1%}" if vol_a == vol_a else "—")
vm2.metric(f"{row_b['symbol']} annualised vol", f"{vol_b:.1%}" if vol_b == vol_b else "—")
vm3.metric("Whole-period correlation", f"{whole_corr:.2f}" if whole_corr == whole_corr else "—")
vm4.metric(f"Whole-period beta ({row_b['symbol']} vs {row_a['symbol']})", f"{whole_beta:.2f}" if whole_beta == whole_beta else "—")

beta_windows = indicators.ROLLING_BETA_WINDOWS[frequency]
beta_results = indicators.rolling_beta_correl(aligned_full["b"], aligned_full["a"], beta_windows)
summary_rows = []
for label, _n in beta_windows:
    beta_series = beta_results[label]["beta"].dropna()
    correl_series = beta_results[label]["correl"].dropna()
    summary_rows.append({
        "Window": label,
        f"Beta ({row_b['symbol']} vs {row_a['symbol']})": beta_series.iloc[-1] if not beta_series.empty else None,
        "Correlation": correl_series.iloc[-1] if not correl_series.empty else None,
    })
summary_df = pd.DataFrame(summary_rows).set_index("Window")
display_summary = summary_df.copy()
for col in display_summary.columns:
    display_summary[col] = display_summary[col].map(lambda x: f"{x:.2f}" if x == x and x is not None else "—")
st.dataframe(display_summary, width="stretch")
st.caption(
    f"Beta here is {row_b['symbol']}'s sensitivity to {row_a['symbol']} (not to a market index) -- "
    "a beta of 1.5 means B has historically moved about 1.5x A's moves. Windows only populate once "
    "enough history has accumulated at the selected frequency."
)

st.divider()

# --------------------------------------------------------------------------
# Interactive stacked chart: normalized overlay, price ratio, rolling
# correlation, rolling z-score -- one figure with a shared x-axis so
# zooming/panning and the crosshair stay in sync across all four panels,
# plus a range slider on the bottom panel.
# --------------------------------------------------------------------------
st.subheader("Interactive overview")

_RESAMPLE_RULE = {"W": "W-FRI", "M": "ME"}


def _resample_series(series: pd.Series) -> pd.Series:
    if resample_freq is None or series.empty:
        return series
    return series.resample(_RESAMPLE_RULE[resample_freq]).last().dropna()


lines = {row_a["symbol"]: (close_a, "Yahoo Finance (price)"), row_b["symbol"]: (close_b, "Yahoo Finance (price)")}
if extra_labels:
    with st.spinner("Fetching extra series..."):
        for lab in extra_labels:
            if lab in label_to_row:
                r = label_to_row[lab]
                series, source = rp.stock_line(r["yf_ticker"], _hist_lookup)
                key = r["symbol"]
            else:
                series, source = rp.broad_index_line(lab, universe, _hist_lookup)
                key = lab
            series = _resample_series(series)
            if not series.empty:
                lines[key] = (series, source)

returns_a_full, returns_b_full = close_a.pct_change(), close_b.pct_change()
ratio_full = pairs.price_ratio(close_a, close_b)
corr_full = pairs.rolling_correlation(returns_a_full, returns_b_full, window).dropna()
zscore_full = pairs.rolling_zscore(ratio_full, window).dropna()

fig = make_subplots(
    rows=4, cols=1, shared_xaxes=True, vertical_spacing=0.035,
    row_heights=[0.32, 0.22, 0.23, 0.23],
    subplot_titles=[
        "Normalized performance overlay (% change)",
        f"Price ratio: {row_a['symbol']} / {row_b['symbol']}",
        f"Rolling {window}-{frequency.lower()[:-2] if frequency != 'Daily' else 'day'} correlation",
        f"Rolling {window}-{frequency.lower()[:-2] if frequency != 'Daily' else 'day'} z-score of the spread",
    ],
)

PALETTE = ["#3D8BFF", "#EF5350", "#00D3A7", "#FFB020", "#B36AE2", "#26A69A"]
for i, (name, (raw_series, _source)) in enumerate(lines.items()):
    sliced = rp.slice_to_timeframe(raw_series, timeframe)
    pct = rp.normalize_pct(sliced)
    if pct.empty:
        continue
    fig.add_trace(
        go.Scatter(
            x=pct.index, y=pct.values, name=f"{name} ({pct.iloc[-1]:+.1f}%)",
            mode="lines", line=dict(width=1.8, color=PALETTE[i % len(PALETTE)]), legendgroup=name,
        ),
        row=1, col=1,
    )
fig.add_hline(y=0, line_dash="dot", line_color=MUTED, row=1, col=1)

ratio_display = pairs.price_ratio(rp.slice_to_timeframe(close_a, timeframe), rp.slice_to_timeframe(close_b, timeframe))
if not ratio_display.empty:
    fig.add_trace(
        go.Scatter(x=ratio_display.index, y=ratio_display.values, mode="lines",
                   line=dict(width=1.6, color=ACCENT_2), name="Ratio", showlegend=False),
        row=2, col=1,
    )
    fig.add_hline(y=ratio_display.mean(), line_dash="dot", line_color=MUTED, row=2, col=1)

corr_display = rp.slice_to_timeframe(corr_full, timeframe) if not corr_full.empty else corr_full
if not corr_display.empty:
    fig.add_trace(
        go.Scatter(x=corr_display.index, y=corr_display.values, mode="lines",
                   line=dict(width=1.6, color=ACCENT), name="Correlation", showlegend=False),
        row=3, col=1,
    )
fig.update_yaxes(range=[-1, 1], row=3, col=1)

z_display = rp.slice_to_timeframe(zscore_full, timeframe) if not zscore_full.empty else zscore_full
if not z_display.empty:
    fig.add_trace(
        go.Scatter(x=z_display.index, y=z_display.values, mode="lines",
                   line=dict(width=1.6, color="#FFB020"), name="Z-score", showlegend=False),
        row=4, col=1,
    )
    fig.add_hline(y=2, line_dash="dot", line_color=DOWN, row=4, col=1)
    fig.add_hline(y=-2, line_dash="dot", line_color=UP, row=4, col=1)
    fig.add_hline(y=0, line_dash="dot", line_color=MUTED, row=4, col=1)

fig.update_xaxes(rangeslider_visible=False)
fig.update_xaxes(rangeslider_visible=True, row=4, col=1, rangeslider_thickness=0.06)
fig.update_layout(
    height=980,
    hovermode="x unified",
    legend=dict(orientation="h", yanchor="bottom", y=1.06, xanchor="left", x=0),
    margin=dict(t=60),
)
for r in range(1, 5):
    fig.update_xaxes(showspikes=True, spikemode="across", spikesnap="cursor", spikethickness=1, row=r, col=1)

st.plotly_chart(fig, width="stretch")
st.caption(
    "Drag on the range slider (bottom panel) or box-zoom on any panel to zoom -- all four panels stay "
    "in sync. Hover anywhere to see values from all panels at once, and click a legend entry to "
    "toggle that line on/off."
)

if corr_display.empty or z_display.empty:
    st.info(
        f"Not enough history yet at this frequency/window to populate the correlation and/or "
        f"z-score panels -- try a shorter rolling window or a lower frequency."
    )

st.caption(
    "Beyond ±2 the spread has strayed unusually far from its own recent average -- classic "
    "pairs-trade entry-zone territory, not a guarantee it reverts."
)

st.divider()

# --------------------------------------------------------------------------
# Return scatter: A's return vs B's return, one point per bar, coloured by
# chronological order, with a simple linear fit line -- the classic
# pairs-trade "how tightly do these two actually move together" picture.
# --------------------------------------------------------------------------
st.subheader(f"{row_a['symbol']} vs {row_b['symbol']} — {frequency.lower()} return scatter")
sliced_a = rp.slice_to_timeframe(close_a, timeframe)
sliced_b = rp.slice_to_timeframe(close_b, timeframe)
returns_a_disp = sliced_a.pct_change().dropna() * 100
returns_b_disp = sliced_b.pct_change().dropna() * 100
aligned = pd.concat({"a": returns_a_disp, "b": returns_b_disp}, axis=1).dropna()
if len(aligned) < 5:
    st.info("Not enough overlapping history in this window for a scatter plot.")
else:
    corr = aligned["a"].corr(aligned["b"])
    slope, intercept = np.polyfit(aligned["a"], aligned["b"], 1)
    order = np.arange(len(aligned))

    fig_scatter = go.Figure()
    fig_scatter.add_trace(
        go.Scatter(
            x=aligned["a"], y=aligned["b"], mode="markers",
            marker=dict(size=6, color=order, colorscale="Viridis", showscale=True,
                        colorbar=dict(title="Earlier → later", ticks="")),
            text=[d.strftime("%Y-%m-%d") for d in aligned.index],
            hovertemplate=f"%{{text}}<br>{row_a['symbol']}: %{{x:.2f}}%<br>{row_b['symbol']}: %{{y:.2f}}%<extra></extra>",
            name="Returns",
        )
    )
    x_range = np.array([aligned["a"].min(), aligned["a"].max()])
    fig_scatter.add_trace(
        go.Scatter(
            x=x_range, y=slope * x_range + intercept, mode="lines",
            line=dict(color=DOWN, dash="dash", width=2), name=f"Linear fit (r={corr:.2f})",
        )
    )
    fig_scatter.update_layout(
        height=440,
        xaxis_title=f"{row_a['symbol']} {frequency.lower()} return (%)",
        yaxis_title=f"{row_b['symbol']} {frequency.lower()} return (%)",
        xaxis_ticksuffix="%", yaxis_ticksuffix="%",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        dragmode="zoom",
    )
    st.plotly_chart(fig_scatter, width="stretch")
    st.caption(
        f"Correlation over this window: {corr:.2f}. Fit: {row_b['symbol']} return ≈ {slope:.2f} × "
        f"{row_a['symbol']} return + {intercept:.3f}pp (the slope here is effectively {row_b['symbol']}'s beta "
        f"to {row_a['symbol']}). Point colour shows chronological order (dark = earlier, light = more recent). "
        "Click-drag to zoom into a region; double-click to reset."
    )

# --------------------------------------------------------------------------
# Cointegration + mean-reversion half-life (up to the last 5 years of
# overlapping data at the selected frequency, independent of the chart
# timeframe selected above)
# --------------------------------------------------------------------------
st.subheader("Cointegration & mean reversion")
st.caption(
    "Computed over up to the last 5 years of overlapping price history at the selected frequency, "
    "regardless of the chart timeframe selected above -- a short window isn't statistically "
    "meaningful for this test."
)

cutoff = close_a.index.max() - relativedelta(years=5)
coint_a = close_a[close_a.index >= cutoff]
coint_b = close_b[close_b.index >= cutoff]

coint_result = pairs.cointegration_test(coint_a, coint_b)
hl = pairs.half_life(pairs.price_ratio(coint_a, coint_b))

if "error" in coint_result:
    st.info(coint_result["error"])
else:
    m1, m2, m3 = st.columns(3)
    m1.metric("Cointegration p-value", f"{coint_result['pvalue']:.3f}")
    m2.metric("Test statistic", f"{coint_result['tstat']:.2f}")
    m3.metric("Half-life (mean reversion)", f"{hl:.0f} {frequency.lower()} bars" if hl else "Not mean-reverting")
    st.markdown(f"<div class='jse-card'>{coint_result['verdict']}</div>", unsafe_allow_html=True)

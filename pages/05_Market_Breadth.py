import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from src import data, indicators
from src import relative_performance as rp
from src import universe as uni
from src.common import bootstrap
from src.theme import ACCENT, ACCENT_2, DOWN, MUTED, UP

bootstrap("Market Breadth", "🌡️")

st.title("🌡️ Market Breadth")
st.caption(
    "How many stocks in the selected market(s) are trading above their moving averages right now -- "
    "a classic gauge of whether a rally or selloff is broad-based or narrow. Pick one or more equity "
    "markets below (defaults to South Africa); for the US specifically, the dedicated **US Sector "
    "Breadth** page also pairs this with the real SPDR sector ETFs."
)

universe = uni.picker("breadth", default_asset_classes=["Equity"], default_markets=["South Africa"], show_sector_filter=False)

scope = st.radio(
    "Universe to scan",
    ["Mega + Large + Mid cap (fast)", "Everything in the current selection (slower, ~1-2 min first run)"],
    horizontal=True,
)
if scope.startswith("Mega"):
    scan_universe = universe[universe["market_cap_tier"].isin(["Mega Cap", "Large Cap", "Mid Cap"])]
else:
    scan_universe = universe

sma_window = st.selectbox("SMA window", [20, 50, 100, 200], index=3)

run = st.button("Run breadth scan", type="primary")

if run:
    progress = st.progress(0.0, text="Fetching price data...")

    def _cb(done, total):
        progress.progress(done / total, text=f"Fetching price data... chunk {done}/{total}")

    hist = data.get_history_bulk(scan_universe["yf_ticker"].tolist(), period="18mo", interval="1d", progress_cb=_cb)
    progress.empty()

    rows = []
    for _, r in scan_universe.iterrows():
        df = hist.get(r["yf_ticker"])
        if df is None or df.empty or len(df) < sma_window:
            continue
        above = indicators.pct_above_sma(df, sma_window)
        if above is None:
            continue
        rows.append(
            {
                "Symbol": r["symbol"],
                "Sector": r["gics_sector"],
                "Industry": r["industry"],
                "Cap Tier": r["market_cap_tier"],
                f"Above {sma_window}-SMA": above,
            }
        )

    if not rows:
        st.error("No breadth data could be computed -- check your data connection (see scripts/test_data_connection.py).")
        st.stop()

    breadth_df = pd.DataFrame(rows)
    st.session_state["breadth_df"] = breadth_df
    st.session_state["breadth_sma"] = sma_window
    st.session_state["breadth_history"] = indicators.breadth_time_series(hist, sma_window)

if "breadth_df" not in st.session_state:
    st.info("Click **Run breadth scan** to compute breadth for the selected universe.")
    st.stop()

breadth_df = st.session_state["breadth_df"]
sma_window = st.session_state["breadth_sma"]
col_name = f"Above {sma_window}-SMA"

total = len(breadth_df)
above_count = int(breadth_df[col_name].sum())
pct = above_count / total * 100 if total else 0

st.divider()
m1, m2, m3 = st.columns(3)
m1.metric("Stocks scanned", total)
m2.metric(f"Above {sma_window}-day SMA", f"{above_count} ({pct:.1f}%)")
m3.metric(f"Below {sma_window}-day SMA", f"{total - above_count} ({100 - pct:.1f}%)")

fig = px.pie(
    values=[above_count, total - above_count],
    names=[f"Above {sma_window}-SMA", f"Below {sma_window}-SMA"],
    color_discrete_sequence=[UP, DOWN],
    hole=0.55,
)
fig.update_layout(height=320, margin=dict(t=10, b=10))
st.plotly_chart(fig, width="stretch")

st.subheader("Breadth by GICS sector")
sector_breadth = (
    breadth_df.groupby("Sector")[col_name]
    .agg(Above="sum", Total="count")
    .assign(Pct=lambda d: (d["Above"] / d["Total"] * 100).round(1))
    .sort_values("Pct", ascending=False)
    .reset_index()
)
fig2 = px.bar(
    sector_breadth,
    x="Pct",
    y="Sector",
    orientation="h",
    text=sector_breadth.apply(lambda r: f"{r['Above']}/{r['Total']} ({r['Pct']}%)", axis=1),
    color="Pct",
    color_continuous_scale=[DOWN, "#8B93A7", UP],
    range_color=[0, 100],
)
fig2.update_layout(height=420, coloraxis_showscale=False, xaxis_title=f"% above {sma_window}-SMA", yaxis_title="")
st.plotly_chart(fig2, width="stretch")

st.subheader("Breadth by industry / subsector")
sector_filter = st.multiselect("Filter to sector(s)", sorted(breadth_df["Sector"].unique()))
industry_scope = breadth_df[breadth_df["Sector"].isin(sector_filter)] if sector_filter else breadth_df
industry_breadth = (
    industry_scope.groupby("Industry")[col_name]
    .agg(Above="sum", Total="count")
    .assign(Pct=lambda d: (d["Above"] / d["Total"] * 100).round(1))
    .sort_values("Pct", ascending=False)
    .reset_index()
)
st.dataframe(industry_breadth, hide_index=True, width="stretch", height=420)

with st.expander("Show underlying stock-level data"):
    st.dataframe(breadth_df.sort_values(col_name, ascending=False), hide_index=True, width="stretch")

# --------------------------------------------------------------------------
# Breadth over time -- how the % of stocks above their SMA has moved across
# the scan's own history window, not just the current snapshot. Built from
# the same price data already fetched above, no extra network calls.
# --------------------------------------------------------------------------
st.subheader("Breadth over time")
breadth_history = st.session_state.get("breadth_history", pd.Series(dtype=float))
if breadth_history.empty:
    st.info(
        "Not enough history in this scan's data to chart breadth over time yet "
        f"(needs more than {sma_window} bars per stock)."
    )
else:
    fig_hist = go.Figure()
    fig_hist.add_trace(
        go.Scatter(
            x=breadth_history.index,
            y=breadth_history.values,
            mode="lines",
            line=dict(color=ACCENT_2, width=1.5),
            fill="tozeroy",
            fillcolor="rgba(61, 139, 255, 0.12)",
            name=f"% above {sma_window}-SMA",
        )
    )
    fig_hist.add_hline(y=50, line_dash="dash", line_color=MUTED, annotation_text="50%", annotation_position="right")
    fig_hist.add_hline(y=80, line_dash="dot", line_color=UP, opacity=0.6, annotation_text="80% (broad strength)", annotation_position="right")
    fig_hist.add_hline(y=20, line_dash="dot", line_color=DOWN, opacity=0.6, annotation_text="20% (broad weakness)", annotation_position="right")
    fig_hist.update_layout(
        height=380,
        yaxis_title=f"% of stocks above {sma_window}-SMA",
        yaxis_range=[0, 100],
        xaxis_title="",
        xaxis=dict(rangeslider=dict(visible=True, thickness=0.06)),
        margin=dict(t=10),
    )
    st.plotly_chart(fig_hist, width="stretch")
    st.caption(
        "How broad-based the market's above/below-SMA split has been over time for this scan's universe "
        "(computed from the same price history fetched above -- no extra data pulled). Readings near 80%+ "
        "mean most stocks are participating in a rally; readings near 20% or below mean a selloff is broad "
        "and few stocks are holding up. Drag the range slider underneath the chart to zoom into a period."
    )

# --------------------------------------------------------------------------
# Cyclical vs. Defensive index -- a sector-rotation / risk-on-risk-off gauge:
# a cap-weighted index of cyclical-sector stocks divided by a cap-weighted
# index of defensive-sector stocks, rebased to 100 at the start of the window.
# --------------------------------------------------------------------------
st.divider()
st.subheader("Cyclical vs. Defensive Index")
st.caption(
    "A cap-weighted index of cyclical-sector stocks divided by a cap-weighted index of "
    "defensive-sector stocks, rebased to 100 at the start of the window. Rising = cyclicals "
    "outperforming (often read as 'risk-on'); falling = defensives outperforming "
    "('risk-off' / flight to safety)."
)

with st.expander("Which sectors count as cyclical vs. defensive?"):
    st.markdown(
        f"**Cyclical:** {', '.join(rp.CYCLICAL_SECTORS)}\n\n"
        f"**Defensive:** {', '.join(rp.DEFENSIVE_SECTORS)}\n\n"
        "This is a standard sector-rotation grouping, not an official JSE index -- cyclicals "
        "swing more with the economic cycle (retail, industrials, mining, banks, property, "
        "tech, energy); defensives tend to sell roughly the same amount regardless of the "
        "economy (food & staples, healthcare, utilities, telecoms/media)."
    )

cd_period = st.selectbox("History window", ["6mo", "1y", "2y", "5y"], index=1, key="cd_period")
run_cd = st.button("Compute Cyclical vs. Defensive index", type="primary", key="run_cd")

if run_cd:
    cd_universe = universe[universe["gics_sector"].isin(rp.CYCLICAL_SECTORS + rp.DEFENSIVE_SECTORS)]
    cd_progress = st.progress(0.0, text="Fetching price data...")

    def _cd_cb(done, total):
        cd_progress.progress(done / total, text=f"Fetching price data... chunk {done}/{total}")

    cd_hist = data.get_history_bulk(cd_universe["yf_ticker"].tolist(), period=cd_period, interval="1d", progress_cb=_cd_cb)
    cd_progress.empty()
    st.session_state["cd_result"] = rp.cyclical_defensive_ratio(universe, cd_hist)
    st.session_state["cd_period_used"] = cd_period

if "cd_result" in st.session_state:
    cd_result = st.session_state["cd_result"]
    ratio = cd_result["ratio"]
    if ratio.empty:
        st.warning("Not enough data to compute the Cyclical vs. Defensive index for this window.")
    else:
        last_val = ratio.iloc[-1]
        cd_m1, cd_m2, cd_m3 = st.columns(3)
        cd_m1.metric("Cyclical / Defensive index", f"{last_val:.1f}", f"{last_val - 100:+.1f} since window start")
        cd_m2.metric("Cyclical constituents", cd_result["n_cyclical"])
        cd_m3.metric("Defensive constituents", cd_result["n_defensive"])

        fig3 = go.Figure()
        fig3.add_trace(go.Scatter(x=ratio.index, y=ratio.values, mode="lines", line=dict(color=ACCENT, width=2)))
        fig3.add_hline(y=100, line_dash="dash", line_color=MUTED, annotation_text="Window start", annotation_position="right")
        fig3.update_layout(
            height=380,
            yaxis_title="Cyclical / Defensive (rebased, start = 100)",
            xaxis_title="",
            margin=dict(t=10),
        )
        st.plotly_chart(fig3, width="stretch")
        st.caption(
            f"Window: {st.session_state['cd_period_used']}. Both sides are cap-weighted composites of this "
            "app's own universe (see the Relative Performance page's caveat on constructed indices)."
        )

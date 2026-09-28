import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src import data
from src import relative_performance as rp
from src import universe as uni
from src.common import bootstrap
from src.theme import DOWN, UP

bootstrap("Relative Performance", "🔀")

st.title("🔀 Relative Performance")
st.caption(
    "Normalized performance comparison -- every line is rebased to 0% at the start of the selected "
    "window, so you can compare things on very different price scales (e.g. a sector vs a single stock). "
    "Each line's legend/table entry shows whether it's a real Yahoo Finance index or a **constructed** "
    "proxy built from that sector/industry's own constituent instruments -- see `src/relative_performance.py` "
    "for the full caveat on sub-index data coverage. Pick your Asset Class / Market below first."
)

universe = uni.picker("rp", default_asset_classes=["Equity"], default_markets=["South Africa"], show_sector_filter=False)

PALETTE = [
    "#3D8BFF", "#00D3A7", "#FFB020", "#EF5350", "#B36AE2", "#26A69A",
    "#F2C744", "#5C9DFF", "#E4738C", "#8DDD9B", "#C08BFF", "#6FCF97",
]


def _hist_lookup(tickers):
    return data.get_history_bulk(tickers, period="max", interval="1d")


def _draw(lines: dict, timeframe: str, height: int = 520, meta_lookup: dict = None):
    if not lines:
        st.warning("No data to show for the current selection.")
        return

    meta_lookup = meta_lookup or {}
    fig = go.Figure()
    rows = []
    for i, (name, (raw_series, source)) in enumerate(lines.items()):
        sliced = rp.slice_to_timeframe(raw_series, timeframe)
        pct = rp.normalize_pct(sliced)
        if pct.empty:
            continue
        indexed = pct + 100  # rebase to 100 at the start of the window, instead of 0%
        color = PALETTE[i % len(PALETTE)]
        fig.add_trace(
            go.Scatter(x=indexed.index, y=indexed.values, name=f"{name} ({indexed.iloc[-1]:.1f})",
                       mode="lines", line=dict(width=1.8, color=color))
        )
        meta = meta_lookup.get(name, {})
        rows.append({
            "Name": meta.get("name", name),
            "Ticker": meta.get("ticker", "—"),
            "Change %": pct.iloc[-1],
            "Data source": source,
        })

    fig.add_hline(y=100, line_dash="dot", line_color="#8B93A7")
    fig.update_layout(
        height=height,
        hovermode="x unified",
        yaxis_title="Indexed performance (100 = start of window)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        dragmode="zoom",
        margin=dict(b=10),
    )
    fig.update_xaxes(
        rangeslider=dict(visible=True, thickness=0.06),
        showspikes=True, spikemode="across", spikesnap="cursor", spikethickness=1,
    )
    fig.update_yaxes(showspikes=True, spikethickness=1)
    st.plotly_chart(fig, width="stretch")
    st.caption(
        "Click-drag on the chart (or the range slider underneath it) to zoom into a specific date range -- "
        "double-click to reset. Double-click a line's legend entry to isolate just that one; single-click "
        "toggles a line on/off."
    )

    if not rows:
        st.info("Not enough history in this window for any of the selected lines.")
        return

    st.markdown("**Performance rankings** (selected timeframe)")
    rank_df = pd.DataFrame(rows).sort_values("Change %", ascending=False).reset_index(drop=True)

    def _color(v):
        return f"color: {UP if v >= 0 else DOWN}; font-weight: 600"

    styler = rank_df.style.format({"Change %": "{:+.2f}%"})
    try:
        styled = styler.map(_color, subset=["Change %"])  # pandas >= 2.1
    except AttributeError:
        styled = styler.applymap(_color, subset=["Change %"])  # pandas < 2.1
    st.dataframe(styled, hide_index=True, width="stretch", height=min(560, 60 + 36 * len(rank_df)))


_primary_market = universe["market"].mode().iloc[0] if not universe.empty else "South Africa"
_default_bench = "JSE All Share" if _primary_market == "South Africa" else f"{_primary_market} (Broad Index)"
if _default_bench not in rp.BROAD_INDEX_CANDIDATES:
    _default_bench = "JSE All Share"

tab_sectors, tab_industries, tab_stocks = st.tabs(
    ["🏛️ Sectors", "🏷️ Industries within a Sector", "📈 Stocks within an Industry"]
)

# --------------------------------------------------------------------------
# Tab 1: whole GICS sectors against each other + broad indices
# --------------------------------------------------------------------------
with tab_sectors:
    st.caption("Compare whole GICS sectors against each other and against the broad market indices.")
    all_sectors = sorted(universe["gics_sector"].unique())
    c1, c2 = st.columns([3, 1])
    with c1:
        chosen_sectors = st.multiselect("Sectors", all_sectors, default=all_sectors, key="rp_sectors")
    with c2:
        include_benchmarks = st.multiselect(
            "Add indices", list(rp.BROAD_INDEX_CANDIDATES.keys()), default=[_default_bench], key="rp_sectors_bench"
        )

    if st.button("Load / refresh sector comparison", type="primary", key="rp_sectors_btn"):
        with st.spinner("Fetching price history (first run per sector can take a little while)..."):
            lines = {}
            for sec in chosen_sectors:
                series, source = rp.sector_line(sec, universe, _hist_lookup)
                if not series.empty:
                    lines[sec] = (series, source)
            for name in include_benchmarks:
                series, source = rp.broad_index_line(name, universe, _hist_lookup)
                if not series.empty:
                    lines[name] = (series, source)
            st.session_state["rp_sector_lines"] = lines

    if "rp_sector_lines" not in st.session_state:
        st.info("Pick your sectors/indices above, then click **Load / refresh sector comparison**.")
    else:
        timeframe = st.radio(
            "Timeframe", rp.TIMEFRAMES, index=rp.TIMEFRAMES.index("1Y"), horizontal=True, key="rp_sectors_tf"
        )
        _draw(st.session_state["rp_sector_lines"], timeframe)

# --------------------------------------------------------------------------
# Tab 2: industries within one sector (e.g. Banks vs Life Insurance vs
# the whole Financials sector)
# --------------------------------------------------------------------------
with tab_industries:
    st.caption("Drill into one sector -- e.g. see Banks alone, Insurance alone, and the whole sector together.")
    sector_choice = st.selectbox("Sector", sorted(universe["gics_sector"].unique()), key="rp_ind_sector")
    industries_in_sector = sorted(universe[universe["gics_sector"] == sector_choice]["industry"].unique())
    c1, c2 = st.columns([3, 1])
    with c1:
        chosen_industries = st.multiselect(
            "Industries", industries_in_sector, default=industries_in_sector, key="rp_industries"
        )
    with c2:
        extra = st.multiselect(
            "Also show",
            ["Whole sector"] + list(rp.BROAD_INDEX_CANDIDATES.keys()),
            default=["Whole sector", _default_bench],
            key="rp_ind_extra",
        )

    if st.button("Load / refresh industry comparison", type="primary", key="rp_ind_btn"):
        with st.spinner("Fetching price history..."):
            lines = {}
            for ind in chosen_industries:
                series, source = rp.industry_line(sector_choice, ind, universe, _hist_lookup)
                if not series.empty:
                    lines[ind] = (series, source)
            if "Whole sector" in extra:
                series, source = rp.sector_line(sector_choice, universe, _hist_lookup)
                if not series.empty:
                    lines[f"{sector_choice} (whole sector)"] = (series, source)
            for name in [x for x in extra if x != "Whole sector"]:
                series, source = rp.broad_index_line(name, universe, _hist_lookup)
                if not series.empty:
                    lines[name] = (series, source)
            st.session_state["rp_industry_lines"] = lines

    if "rp_industry_lines" not in st.session_state:
        st.info("Pick a sector and its industries above, then click **Load / refresh industry comparison**.")
    else:
        timeframe = st.radio(
            "Timeframe", rp.TIMEFRAMES, index=rp.TIMEFRAMES.index("1Y"), horizontal=True, key="rp_ind_tf"
        )
        _draw(st.session_state["rp_industry_lines"], timeframe)

# --------------------------------------------------------------------------
# Tab 3: individual stocks within one industry
# --------------------------------------------------------------------------
with tab_stocks:
    st.caption(
        "Compare any stocks head-to-head -- across any sector or industry, your choice. Optionally narrow "
        "the list below by sector first, or just search the whole universe by name/ticker."
    )
    sector_narrow = st.multiselect(
        "Narrow by sector (optional -- leave empty to search every instrument in this selection)",
        sorted(universe["gics_sector"].unique()), default=[], key="rp_stk_sector_narrow",
    )
    stock_pool = universe if not sector_narrow else universe[universe["gics_sector"].isin(sector_narrow)]
    label_to_row = {f"{r['symbol']} — {r['name']}": r for _, r in stock_pool.iterrows()}
    pool_labels = sorted(label_to_row.keys())

    if "rp_stocks_ms" not in st.session_state:
        st.session_state["rp_stocks_ms"] = []
    # drop any previously-picked stocks that fell out of the pool after narrowing by sector
    st.session_state["rp_stocks_ms"] = [l for l in st.session_state["rp_stocks_ms"] if l in pool_labels]

    bc1, bc2, bc3 = st.columns([1, 1, 4])
    with bc1:
        if st.button("Select all", key="rp_stk_selectall", help=f"Select all {len(pool_labels)} stocks currently listed below"):
            st.session_state["rp_stocks_ms"] = pool_labels
    with bc2:
        if st.button("Clear all", key="rp_stk_clearall"):
            st.session_state["rp_stocks_ms"] = []

    chosen_labels = st.multiselect(
        "Stocks (type to search by name or ticker)", pool_labels, key="rp_stocks_ms"
    )
    if len(chosen_labels) > 30:
        st.caption(f"{len(chosen_labels)} stocks selected -- fetching and charting that many may take a while and get crowded to read.")

    c1, c2 = st.columns(2)
    with c1:
        extra_sectors = st.multiselect(
            "Also show sector line(s)", sorted(universe["gics_sector"].unique()), default=[], key="rp_stk_extra_sectors"
        )
    with c2:
        extra_idx = st.multiselect(
            "Also show index(es)", list(rp.BROAD_INDEX_CANDIDATES.keys()), default=[], key="rp_stk_extra_idx"
        )

    if st.button("Load / refresh stock comparison", type="primary", key="rp_stk_btn"):
        if not chosen_labels and not extra_sectors and not extra_idx:
            st.warning("Pick at least one stock, sector, or index to compare.")
        else:
            with st.spinner("Fetching price history..."):
                lines = {}
                meta = {}
                for label in chosen_labels:
                    row = label_to_row[label]
                    series, source = rp.stock_line(row["yf_ticker"], _hist_lookup)
                    if not series.empty:
                        lines[row["symbol"]] = (series, source)
                        meta[row["symbol"]] = {"name": row["name"], "ticker": row["symbol"]}
                for sec in extra_sectors:
                    series, source = rp.sector_line(sec, universe, _hist_lookup)
                    if not series.empty:
                        lines[f"{sec} (sector)"] = (series, source)
                for name in extra_idx:
                    series, source = rp.broad_index_line(name, universe, _hist_lookup)
                    if not series.empty:
                        lines[name] = (series, source)
                st.session_state["rp_stock_lines"] = lines
                st.session_state["rp_stock_meta"] = meta

    if "rp_stock_lines" not in st.session_state:
        st.info("Pick your stocks (and optionally sector/index lines) above, then click **Load / refresh stock comparison**.")
    else:
        timeframe = st.radio(
            "Timeframe", rp.TIMEFRAMES, index=rp.TIMEFRAMES.index("1Y"), horizontal=True, key="rp_stk_tf"
        )
        _draw(st.session_state["rp_stock_lines"], timeframe, meta_lookup=st.session_state.get("rp_stock_meta", {}))

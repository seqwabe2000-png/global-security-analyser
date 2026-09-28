"""
Streamlit building blocks shared by the Portfolio pages (20-25):
settings sidebar, portfolio pickers, cached market-data loader, number
formatting, formula expanders and the chart functions.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src import data, indicators
from src import portfolio as pf
from src import universe as uni
from src.theme import ACCENT, BORDER, DOWN, MUTED, TEXT, UP

# Categorical order (dark-surface steps, validated palette) -- assigned in
# fixed order, never cycled past 8 (extra series fold into "Other").
SERIES = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"]
DIVERGING = [[0.0, "#3987e5"], [0.5, "#3a3f4b"], [1.0, "#e66767"]]  # -1 blue .. 0 grey .. +1 red

RF_DEFAULTS = {"ZAR": 0.0725, "USD": 0.0375, "LOCAL": 0.0725}


# --------------------------------------------------------------------------
# Persistent settings (survive page switches)
# --------------------------------------------------------------------------
def _persist(key, default):
    store = f"_keep_{key}"
    if store in st.session_state and key not in st.session_state:
        st.session_state[key] = st.session_state[store]
    elif key not in st.session_state:
        st.session_state[key] = default


def _keep(key):
    st.session_state[f"_keep_{key}"] = st.session_state[key]


def settings_sidebar() -> dict:
    """Global risk settings shown in the sidebar of every portfolio page."""
    sb = st.sidebar
    sb.markdown("### ⚙️ Risk settings")
    defaults = {"pf_base": "ZAR", "pf_freq": "Weekly", "pf_lookback": "5Y", "pf_conf": 0.95, "pf_h": 10,
                "pf_rf_zar": RF_DEFAULTS["ZAR"] * 100, "pf_rf_usd": RF_DEFAULTS["USD"] * 100,
                "pf_bench": list(pf.DEFAULT_BENCHMARKS.keys())}
    for k, v in defaults.items():
        _persist(k, v)
    base = sb.radio("Base currency", ["ZAR", "USD", "LOCAL"], key="pf_base", horizontal=True,
                    on_change=_keep, args=("pf_base",),
                    help="All prices are converted into this currency before returns are computed, so FX "
                         "(rand) risk is included. LOCAL = each asset's own currency, no FX.")
    freq = sb.radio("Return frequency", ["Daily", "Weekly", "Monthly"], key="pf_freq", horizontal=True,
                    on_change=_keep, args=("pf_freq",),
                    help="Weekly is the default: JSE, US and crypto close at different times, which biases "
                         "daily cross-market correlations downward.")
    lb = sb.select_slider("Lookback", ["1Y", "2Y", "3Y", "5Y", "10Y", "Max"], key="pf_lookback",
                          on_change=_keep, args=("pf_lookback",))
    c1, c2 = sb.columns(2)
    conf = c1.selectbox("VaR confidence", [0.90, 0.95, 0.975, 0.99], key="pf_conf", format_func=lambda x: f"{x:.1%}",
                        on_change=_keep, args=("pf_conf",))
    h = c2.number_input("VaR horizon (days)", 1, 250, key="pf_h", on_change=_keep, args=("pf_h",))
    c3, c4 = sb.columns(2)
    rf_zar = c3.number_input("Rf ZAR %", 0.0, 25.0, step=0.05, key="pf_rf_zar", on_change=_keep, args=("pf_rf_zar",),
                             help="SA 3-month T-bill (used when base = ZAR / LOCAL).")
    rf_usd = c4.number_input("Rf USD %", 0.0, 15.0, step=0.05, key="pf_rf_usd", on_change=_keep, args=("pf_rf_usd",),
                             help="US 3-month T-bill (used when base = USD).")
    all_b = {**pf.DEFAULT_BENCHMARKS, **pf.EXTRA_BENCHMARKS}
    bsel = sb.multiselect("Benchmarks", list(all_b.keys()), key="pf_bench", on_change=_keep, args=("pf_bench",))
    if sb.button("🔄 Refresh prices", width="stretch", help="Re-download from Yahoo Finance, ignoring the 6h cache."):
        st.session_state["pf_refresh"] = st.session_state.get("pf_refresh", 0) + 1
        st.cache_data.clear()
    years = None if lb == "Max" else float(lb[:-1])
    rf = (rf_usd if base == "USD" else rf_zar) / 100
    return {"base": base, "frequency": freq, "lookback": lb, "years": years, "conf": float(conf), "h": int(h),
            "rf": rf, "benchmarks": {b: all_b[b] for b in (bsel or ["S&P 500"])},
            "refresh": st.session_state.get("pf_refresh", 0)}


# --------------------------------------------------------------------------
# Market data (cached)
# --------------------------------------------------------------------------
@st.cache_data(ttl=1800, show_spinner=False)
def _market(tickers: tuple, bench_items: tuple, base: str, frequency: str, years, rf: float, refresh: int):
    force = refresh > 0 and st.session_state.get("_pf_last_refresh") != refresh
    def hist_fn(ts):
        return data.get_history_bulk(ts, period="max", interval="1d", force_refresh=force)
    md = pf.build_market_data(list(tickers), dict(bench_items), base=base, frequency=frequency,
                              lookback_years=years, rf_annual=rf, history_fn=hist_fn,
                              instruments=uni.load_instruments())
    return md


def market_data(tickers, cfg) -> pf.MarketData:
    tickers = tuple(sorted({t for t in tickers if t}))
    with st.spinner(f"Loading prices for {len(tickers)} instruments (cached 30 min)..."):
        md = _market(tickers, tuple(cfg["benchmarks"].items()), cfg["base"], cfg["frequency"], cfg["years"],
                     cfg["rf"], cfg["refresh"])
    st.session_state["_pf_last_refresh"] = cfg["refresh"]
    return md


def data_quality_box(md: pf.MarketData, holdings: pd.DataFrame | None = None):
    issues = []
    if md.missing:
        issues.append(f"**No price data** for: {', '.join(md.missing)} -- excluded (their weight is re-spread "
                      "over the rest). Fix the ticker in the Portfolio Builder.")
    if holdings is not None:
        blank = holdings[holdings["ticker"] == ""]
        if not blank.empty:
            issues.append(f"**No ticker** for: {', '.join(blank['name'])} -- excluded.")
    for label, t in cfg_proxy_notes(md):
        issues.append(f"Benchmark **{label}**: index not available, using proxy **{t}**.")
    for t, n in md.notes.items():
        issues.append(f"{t}: {'; '.join(n)}")
    short = [t for t in md.returns.columns if t != pf.CASH_TICKER and md.returns[t].notna().sum() < 0.6 * len(md.returns)]
    if short:
        issues.append(f"Short history (< 60% of lookback): {', '.join(short)} -- pairwise statistics use what exists.")
    if issues:
        with st.expander(f"⚠️ Data notes ({len(issues)})", expanded=bool(md.missing)):
            for i in issues:
                st.markdown(f"- {i}")


def cfg_proxy_notes(md):
    out = []
    for label, used in md.bench_used.items():
        orig = {**pf.DEFAULT_BENCHMARKS, **pf.EXTRA_BENCHMARKS}.get(label)
        if orig and used != orig:
            out.append((label, used))
    return out


# --------------------------------------------------------------------------
# Session portfolios
# --------------------------------------------------------------------------
def working() -> dict:
    """{kind: {name: holdings_df}} for the current session."""
    if "pf_working" not in st.session_state:
        st.session_state["pf_working"] = {k: {} for k in pf.KINDS}
    return st.session_state["pf_working"]


def available(kind: str) -> list:
    names = list(working()[kind].keys())
    names += [n for n in pf.list_saved(kind) if n not in names]
    return names


def get_holdings(kind: str, name: str) -> pd.DataFrame:
    w = working()[kind]
    if name in w:
        return w[name].copy()
    h, _ = pf.load_portfolio(kind, name)
    return h


def pick(kind: str, label: str, key: str, container=st) -> tuple[str | None, pd.DataFrame | None]:
    names = available(kind)
    if not names:
        container.info(f"No {kind} portfolios yet -- create one on the **Portfolio Builder** page.")
        return None, None
    _persist(key, names[0])
    if st.session_state[key] not in names:
        st.session_state[key] = names[0]
    name = container.selectbox(label, names, key=key, on_change=_keep, args=(key,))
    return name, get_holdings(kind, name)


# --------------------------------------------------------------------------
# Formatting
# --------------------------------------------------------------------------
def pct(x, d=2):
    return "—" if x is None or (isinstance(x, float) and not np.isfinite(x)) else f"{x * 100:,.{d}f}%"


def num(x, d=2):
    return "—" if x is None or (isinstance(x, float) and not np.isfinite(x)) else f"{x:,.{d}f}"


def imetric(container, label, value, sub=None, help=None, **_):
    """Metric whose delta line is informational (grey, no arrow)."""
    try:
        container.metric(label, value, sub, delta_color="off", help=help, delta_arrow="off")
    except TypeError:  # older Streamlit without delta_arrow
        container.metric(label, value, sub, delta_color="off", help=help)


def money_short(x, ccy="ZAR"):
    sym = {"ZAR": "R", "USD": "$", "LOCAL": ""}.get(ccy, ccy)
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "—"
    a = abs(x)
    s = f"{a / 1e9:.2f}bn" if a >= 1e9 else f"{a / 1e6:.2f}m" if a >= 1e6 else f"{a / 1e3:.1f}k" if a >= 1e3 else f"{a:.0f}"
    return f"{'-' if x < 0 else ''}{sym}{s}"


def money(x, ccy="R"):
    sym = {"ZAR": "R", "USD": "$", "LOCAL": ""}.get(ccy, ccy)
    return "—" if x is None or (isinstance(x, float) and not np.isfinite(x)) else f"{sym}{x:,.0f}"


def pct_cols(df: pd.DataFrame, cols, d=2) -> dict:
    return {c: st.column_config.NumberColumn(c, format=f"%.{d}f%%") for c in cols if c in df.columns}


def as_pct(df: pd.DataFrame, cols) -> pd.DataFrame:
    df = df.copy()
    for c in cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce") * 100
    return df


def formulas(*keys, title="📐 How these numbers are calculated", expanded=False):
    with st.expander(title, expanded=expanded):
        for k in keys:
            latex, text = pf.FORMULAS[k]
            st.markdown(f"**{k}**")
            st.latex(latex)
            st.caption(text)


# --------------------------------------------------------------------------
# Charts
# --------------------------------------------------------------------------
def _layout(fig, h=380, **kw):
    kw.setdefault("hovermode", fig.layout.hovermode or "closest")
    fig.update_layout(height=h, margin=dict(l=10, r=10, t=40, b=10),
                      legend=dict(orientation="h", y=1.08, x=0), **kw)
    return fig


def bar_weight_vs_risk(rc: pd.DataFrame, labels: dict | None = None, top: int = 25):
    d = rc.copy()
    d = d.reindex(d["% risk"].abs().sort_values(ascending=False).index).head(top)
    names = [labels.get(t, t) if labels else t for t in d.index]
    fig = go.Figure()
    fig.add_bar(y=names, x=d["weight"] * 100, name="Weight", orientation="h", marker_color=SERIES[0],
                hovertemplate="%{y}<br>Weight %{x:.2f}%<extra></extra>")
    fig.add_bar(y=names, x=d["% risk"] * 100, name="% of portfolio risk", orientation="h", marker_color=SERIES[1],
                hovertemplate="%{y}<br>Risk share %{x:.2f}%<extra></extra>")
    fig.update_layout(barmode="group", bargap=0.25, bargroupgap=0.08, yaxis=dict(autorange="reversed"),
                      xaxis_title="% of portfolio")
    return _layout(fig, h=max(320, 26 * len(d) + 80))


def corr_heatmap(corr: pd.DataFrame, h=None):
    n = len(corr)
    fig = go.Figure(go.Heatmap(z=corr.values, x=corr.columns, y=corr.index, zmin=-1, zmax=1,
                               colorscale=DIVERGING, xgap=1, ygap=1,
                               text=np.round(corr.values, 2), texttemplate="%{text}" if n <= 20 else None,
                               hovertemplate="%{y} × %{x}<br>ρ = %{z:.2f}<extra></extra>",
                               colorbar=dict(title="ρ")))
    fig.update_layout(yaxis=dict(autorange="reversed"))
    return _layout(fig, h=h or max(420, 22 * n + 120))


def line_chart(df: pd.DataFrame, title_y: str, pct_axis=True, h=360, colors=None, dash=None):
    fig = go.Figure()
    cols = list(df.columns)
    for i, c in enumerate(cols[:8]):
        color = (colors or {}).get(c, SERIES[i % 8])
        fig.add_scatter(x=df.index, y=df[c] * (100 if pct_axis else 1), name=str(c), mode="lines",
                        line=dict(width=2, color=color, dash=(dash or {}).get(c)),
                        hovertemplate="%{x|%Y-%m-%d}<br>" + str(c) + ": %{y:.2f}" + ("%" if pct_axis else "") + "<extra></extra>")
    fig.update_layout(yaxis_title=title_y, hovermode="x unified")
    if pct_axis:
        fig.update_yaxes(ticksuffix="%")
    return _layout(fig, h=h)


def drawdown_chart(dd: pd.Series, name="Portfolio", h=260):
    fig = go.Figure(go.Scatter(x=dd.index, y=dd * 100, fill="tozeroy", mode="lines", name=name,
                               line=dict(color=DOWN, width=1.5), fillcolor="rgba(230,103,103,0.25)",
                               hovertemplate="%{x|%Y-%m-%d}<br>Drawdown %{y:.2f}%<extra></extra>"))
    fig.update_yaxes(ticksuffix="%", title="Drawdown")
    return _layout(fig, h=h, showlegend=False)


def var_hist_chart(dist: np.ndarray | pd.Series, lines: dict, title_x: str, h=340):
    x = np.asarray(dist) * 100
    fig = go.Figure(go.Histogram(x=x, nbinsx=80, marker_color=SERIES[0], opacity=0.85, name="Frequency",
                                 hovertemplate="%{x:.2f}%<br>count %{y}<extra></extra>"))
    palette = [SERIES[1], SERIES[3], SERIES[4], SERIES[6], SERIES[7]]
    for i, (label, v) in enumerate(lines.items()):
        if v is None or not np.isfinite(v):
            continue
        fig.add_vline(x=-v * 100, line_color=palette[i % len(palette)], line_dash="dash",
                      annotation=dict(text=f"{label} {v * 100:.2f}%", yshift=-18 * i, xanchor="right",
                                      font=dict(color=palette[i % len(palette)])),
                      annotation_position="top left")
    fig.update_xaxes(ticksuffix="%", title=title_x)
    fig.update_yaxes(title="Frequency")
    return _layout(fig, h=h, showlegend=False)


def scatter_risk_return(df: pd.DataFrame, highlight: dict | None = None, frontier: pd.DataFrame | None = None,
                        cloud: pd.DataFrame | None = None, h=460, size_col=None):
    """df: index=label, columns vol, return (fractions)."""
    fig = go.Figure()
    if cloud is not None and not cloud.empty:
        fig.add_scatter(x=cloud["vol"] * 100, y=cloud["return"] * 100, mode="markers", name="Random portfolios",
                        marker=dict(size=4, color=MUTED, opacity=0.25), hoverinfo="skip")
    if frontier is not None and not frontier.empty:
        fig.add_scatter(x=frontier["vol"] * 100, y=frontier["return"] * 100, mode="lines", name="Efficient frontier",
                        line=dict(color=ACCENT, width=2))
    if not df.empty:
        sizes = 10 if size_col is None else (8 + 30 * np.sqrt(df[size_col].clip(lower=0) / max(df[size_col].max(), 1e-9)))
        fig.add_scatter(x=df["vol"] * 100, y=df["return"] * 100, mode="markers+text" if len(df) <= 15 else "markers",
                        name="Assets", text=df.index, textposition="top center", textfont=dict(size=10, color=MUTED),
                        marker=dict(size=sizes, color=SERIES[0], line=dict(color="#131722", width=2)),
                        hovertemplate="%{text}<br>Vol %{x:.1f}%<br>Return %{y:.1f}%<extra></extra>")
    for i, (label, (v, r)) in enumerate((highlight or {}).items()):
        fig.add_scatter(x=[v * 100], y=[r * 100], mode="markers", name=label, text=[label],
                        marker=dict(size=16, symbol="diamond", color=SERIES[(i + 1) % 8], line=dict(color="#131722", width=2)),
                        hovertemplate=label + "<br>Vol %{x:.2f}%<br>Return %{y:.2f}%<extra></extra>")
    fig.update_xaxes(title="Annualised volatility", ticksuffix="%")
    fig.update_yaxes(title="Annualised return", ticksuffix="%")
    return _layout(fig, h=h)


def fan_chart(proj: dict, ppy: int, ccy: str, h=420):
    p = proj["paths_pct"]
    x = np.arange(len(p)) / ppy
    fig = go.Figure()
    fig.add_scatter(x=x, y=p["p95"], line=dict(width=0), showlegend=False, hoverinfo="skip")
    fig.add_scatter(x=x, y=p["p5"], fill="tonexty", fillcolor="rgba(57,135,229,0.15)", line=dict(width=0),
                    name="5th–95th pct", hoverinfo="skip")
    fig.add_scatter(x=x, y=p["p75"], line=dict(width=0), showlegend=False, hoverinfo="skip")
    fig.add_scatter(x=x, y=p["p25"], fill="tonexty", fillcolor="rgba(57,135,229,0.35)", line=dict(width=0),
                    name="25th–75th pct", hoverinfo="skip")
    fig.add_scatter(x=x, y=p["p50"], line=dict(color=SERIES[0], width=2.5), name="Median",
                    hovertemplate="Year %{x:.1f}<br>Median %{y:,.0f}<extra></extra>")
    fig.add_scatter(x=x, y=proj["invested"], line=dict(color=MUTED, width=1.5, dash="dot"), name="Capital invested",
                    hovertemplate="Year %{x:.1f}<br>Invested %{y:,.0f}<extra></extra>")
    fig.update_xaxes(title="Years")
    fig.update_yaxes(title=f"Portfolio value ({ccy})")
    return _layout(fig, h=h, hovermode="x unified")


def contribution_bar(df: pd.DataFrame, value_col: str, label_col=None, h=None, title_x="Contribution"):
    d = df.copy()
    labels = d[label_col] if label_col else d.index
    colors = [UP if v >= 0 else DOWN for v in d[value_col]]
    fig = go.Figure(go.Bar(x=d[value_col] * 100, y=labels, orientation="h", marker_color=colors,
                           hovertemplate="%{y}<br>%{x:.2f}%<extra></extra>"))
    fig.update_xaxes(ticksuffix="%", title=title_x)
    fig.update_layout(yaxis=dict(autorange="reversed"))
    return _layout(fig, h=h or max(300, 22 * len(d) + 80), showlegend=False)


# --------------------------------------------------------------------------
# Single-instrument stats tabs (reused from the analyser's DoR / ATR% /
# Rolling Stats & Beta pages, in base or local currency)
# --------------------------------------------------------------------------
def single_asset_tabs(ticker: str, md: pf.MarketData, label: str, key: str, port_series: pd.Series | None = None):
    ohlc = md.ohlc.get(ticker)
    if ohlc is None or ohlc.empty:
        st.warning(f"No OHLC data for {ticker}.")
        return
    t1, t2, t3, t4 = st.tabs(["📉 Distribution of returns", "🌪️ Volatility & ATR%", "🧮 Beta & correlation",
                              "📈 Price & drawdown"])
    tf = st.session_state.get("pf_freq", "Weekly")
    tf_map = {"Daily": None, "Weekly": "W", "Monthly": "M"}
    raw = ohlc.copy()
    raw_clean, _ = pf.clean_price_series(raw["Adj Close"] if "Adj Close" in raw else raw["Close"])
    scale = (raw_clean / raw["Adj Close"].reindex(raw_clean.index)).reindex(raw.index).ffill().fillna(1)
    for c in ("Open", "High", "Low", "Close", "Adj Close"):
        if c in raw:
            raw[c] = raw[c] * scale
    years = st.session_state.get("pf_lookback", "5Y")
    if years != "Max":
        raw = raw[raw.index > raw.index.max() - pd.DateOffset(years=int(years[:-1]))]
    df = raw if tf_map[tf] is None else data.resample_ohlc(raw, tf_map[tf])

    with t1:
        rtype = st.radio("Return series", ["C-C Return", "H-L Return", "O-C Return", "C-O Return"], horizontal=True,
                         key=f"{key}_rt", help="Local-currency OHLC returns (FX excluded) -- same as the analyser's DoR page.")
        series = indicators.compute_returns(df)[rtype]
        ppy = indicators.PERIODS_PER_YEAR[tf]
        stats_ = indicators.descriptive_stats(series, ppy)
        if not stats_:
            st.info("Not enough data.")
        else:
            m = st.columns(5)
            m[0].metric("Mean", pct(stats_["Mean"], 3))
            m[1].metric("Std dev", pct(stats_["Standard Deviation"], 3))
            m[2].metric("Skew", num(stats_["Skewness"]))
            m[3].metric("Excess kurtosis", num(stats_["Kurtosis"]))
            m[4].metric("Ann. std dev", pct(stats_["Annualised Std Dev"], 1), help=f"Annualised mean {pct(stats_['Annualised Mean'], 1)}")
            bins = indicators.distribution_bins(series)
            c1, c2 = st.columns([2, 1])
            with c1:
                colors = [DOWN if l.startswith("Less") else (UP if l.startswith("Greater") else SERIES[0]) for l in bins["Range"]]
                fig = go.Figure(go.Bar(x=bins["Range"], y=bins["Frequency"], marker_color=colors,
                                       hovertemplate="%{x}<br>%{y} periods<extra></extra>"))
                fig.update_layout(xaxis_tickangle=-40, xaxis_title="Return bucket (mean ± k·σ)", yaxis_title="Frequency")
                st.plotly_chart(_layout(fig, 380, showlegend=False), width="stretch", key=f"{key}_hist")
            with c2:
                order = ["Mean", "Standard Error", "Median", "Standard Deviation", "Sample Variance", "Kurtosis",
                         "Skewness", "Range", "Minimum", "Maximum", "Count", "Annualised Mean", "Annualised Std Dev"]
                rows = [(k, (f"{int(stats_[k])}" if k == "Count" else (num(stats_[k], 3) if k in ("Kurtosis", "Skewness") else pct(stats_[k], 3)))) for k in order]
                st.dataframe(pd.DataFrame(rows, columns=["Statistic", "Value"]), hide_index=True, width="stretch", height=420)
            pt = indicators.percentile_table(series)
            sel = pt[pt["Percentile"].isin([1, 5, 10, 25, 50, 75, 90, 95, 99])].set_index("Percentile").T
            sel.columns = [f"P{c}" for c in sel.columns]
            st.markdown("**Percentiles** (empirical -- the P5 value is the historical-VaR point for one period)")
            st.dataframe((sel * 100).round(2).astype(str) + "%", width="stretch")
            ed = indicators.empirical_distribution(series)
            e1, e2 = st.columns(2)
            e1.markdown("**Actual vs. normal distribution**")
            e1.dataframe(ed["bands"], hide_index=True, width="stretch")
            e2.markdown("**Positive / negative periods**")
            e2.dataframe(ed["buckets"], hide_index=True, width="stretch")

    with t2:
        ppy = pf.PERIODS_PER_YEAR[tf]
        r_base = md.returns[ticker].dropna() if ticker in md.returns else pd.Series(dtype=float)
        wins = indicators.ROLLING_VOL_WINDOWS[tf]
        vol = pd.DataFrame({f"{w}-period": r_base.rolling(w).std() * np.sqrt(ppy) for w in wins})
        st.markdown(f"**Rolling annualised volatility** ({md.base} returns, {tf.lower()})")
        if not vol.dropna(how="all").empty:
            last = vol.dropna(how="all").iloc[-1]
            cc = st.columns(len(wins) + 1)
            for c, w in zip(cc, wins):
                c.metric(f"{w}-period vol", pct(last[f"{w}-period"], 1))
            cc[-1].metric("Full-lookback vol", pct(r_base.std() * np.sqrt(ppy), 1))
            st.plotly_chart(line_chart(vol, "Annualised volatility"), width="stretch", key=f"{key}_rv")
        # vol cone: distribution of rolling vol per window
        cone = []
        for w in wins:
            s = (r_base.rolling(w).std() * np.sqrt(ppy)).dropna()
            if len(s):
                cone.append({"window": f"{w}", "min": s.min(), "p25": s.quantile(.25), "median": s.median(),
                             "p75": s.quantile(.75), "max": s.max(), "current": s.iloc[-1]})
        if cone:
            cdf = pd.DataFrame(cone)
            fig = go.Figure()
            for i, c in enumerate(["min", "p25", "median", "p75", "max"]):
                fig.add_scatter(x=cdf["window"], y=cdf[c] * 100, name=c, mode="lines",
                                line=dict(color=MUTED if c in ("min", "max") else SERIES[0], width=1.5 if c != "median" else 2.5,
                                          dash="dot" if c in ("min", "max") else ("dash" if c in ("p25", "p75") else None)))
            fig.add_scatter(x=cdf["window"], y=cdf["current"] * 100, name="current", mode="markers+lines",
                            marker=dict(size=10, color=SERIES[1]), line=dict(color=SERIES[1], width=2))
            fig.update_yaxes(ticksuffix="%", title="Annualised vol")
            fig.update_xaxes(title=f"Window ({tf.lower()} periods)", type="category")
            st.markdown("**Volatility cone** -- is today's volatility high or low versus its own history?")
            st.plotly_chart(_layout(fig, 340), width="stretch", key=f"{key}_cone")
        st.markdown("**Average True Range %** (local-currency OHLC, as on the ATR% page)")
        atr = indicators.average_true_range_pct(df, indicators.ATRP_HORIZONS[tf])
        a1, a2 = st.columns([1, 1.4])
        a1.dataframe(atr.assign(**{"Avg True Range %": atr["Avg True Range %"].map(lambda x: pct(x, 3))}),
                     hide_index=True, width="stretch")
        trp = indicators.true_range_pct(df).dropna().tail(500)
        fig = go.Figure(go.Scatter(x=trp.index, y=trp * 100, mode="lines", line=dict(color=SERIES[0], width=1.2),
                                   name="TR%", hovertemplate="%{x|%Y-%m-%d}<br>TR %{y:.2f}%<extra></extra>"))
        fig.add_hline(y=trp.mean() * 100, line_dash="dot", line_color=MUTED, annotation_text="mean")
        fig.update_yaxes(ticksuffix="%", title="True Range %")
        a2.plotly_chart(_layout(fig, 320, showlegend=False), width="stretch", key=f"{key}_atr")

    with t3:
        r_base = md.returns[ticker] if ticker in md.returns else pd.Series(dtype=float)
        benches = md.bench_returns.copy()
        if port_series is not None:
            benches["Portfolio"] = port_series
        rows = []
        for b in benches.columns:
            beta, corr = pf.beta_to(r_base, benches[b])
            rows.append({"vs": b, "beta": beta, "correlation": corr, "R²": corr ** 2 if corr == corr else np.nan})
        st.dataframe(pd.DataFrame(rows).round(3), hide_index=True, width="stretch")
        ppy = pf.PERIODS_PER_YEAR[tf]
        win = {"Daily": 126, "Weekly": 26, "Monthly": 12}[tf]
        win = st.slider("Rolling window (periods)", max(6, win // 3), win * 4, win, key=f"{key}_bw")
        rb = pd.DataFrame({b: r_base.rolling(win).cov(benches[b]) / benches[b].rolling(win).var() for b in benches.columns})
        rc = pd.DataFrame({b: r_base.rolling(win).corr(benches[b]) for b in benches.columns})
        c1, c2 = st.columns(2)
        f1 = line_chart(rb, "Rolling beta", pct_axis=False, h=320)
        f1.add_hline(y=1, line_dash="dot", line_color=MUTED)
        c1.plotly_chart(f1, width="stretch", key=f"{key}_rb")
        f2 = line_chart(rc, "Rolling correlation", pct_axis=False, h=320)
        f2.update_yaxes(range=[-1, 1])
        c2.plotly_chart(f2, width="stretch", key=f"{key}_rc")
        formulas("Beta", "Correlation")

    with t4:
        pb = md.prices_base[ticker].dropna() if ticker in md.prices_base else pd.Series(dtype=float)
        if years != "Max" and len(pb):
            pb = pb[pb.index > pb.index.max() - pd.DateOffset(years=int(years[:-1]))]
        if len(pb):
            pl = md.prices_local[ticker].reindex(pb.index)
            comp = pd.DataFrame({f"{md.base} (incl. FX)": pb / pb.iloc[0] - 1, "Local currency": pl / pl.iloc[0] - 1})
            st.plotly_chart(line_chart(comp, "Cumulative return"), width="stretch", key=f"{key}_px")
            st.plotly_chart(drawdown_chart(pb / pb.cummax() - 1, label), width="stretch", key=f"{key}_dd")
            prs = indicators.period_returns(md.prices_local[ticker].dropna())
            if prs:
                st.dataframe(pd.DataFrame([{k: f"{v:.2f}%" for k, v in prs.items()}]), hide_index=True, width="stretch")

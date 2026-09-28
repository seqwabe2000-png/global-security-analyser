import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src import portfolio as pf
from src import portfolio_ui as pui
from src import universe as uni
from src.common import bootstrap

bootstrap("Constituent Analysis", "🔬")
cfg = pui.settings_sidebar()
instruments = uni.load_instruments()

st.title("🔬 Constituent Analysis — single & multiple holdings")
st.caption("The analyser's statistics, distribution-of-returns and volatility tools, applied to one or several "
           "constituents -- plus how they behave together and inside the portfolio.")

focus = st.session_state.pop("pf_focus", None)
KIND_LBL = {"live": "Live portfolio", "model": "Model portfolio", "watchlist": "Watchlist", "any": "Any instrument"}
kinds = ["live", "model", "watchlist", "any"]
if focus:
    st.session_state["ca_kind"] = focus["kind"]
c1, c2 = st.columns([1, 1.4])
kind = c1.radio("Source", kinds, format_func=KIND_LBL.get, horizontal=True, key="ca_kind")
h = None
if kind != "any":
    if focus and focus.get("name") in pui.available(kind):
        st.session_state[f"ca_pick_{kind}"] = focus["name"]
    with c2:
        pname, h = pui.pick(kind, KIND_LBL[kind], f"ca_pick_{kind}")
    if h is None:
        st.stop()
    h = h[h["ticker"] != ""].sort_values("weight", ascending=False)
    options = list(dict.fromkeys(h["ticker"]))
    names = {r.ticker: (r.name or r.ticker)[:30] for r in h.itertuples()}
else:
    lab = {f"{r.symbol} — {r.name} ({r.market})": r.yf_ticker for r in instruments.itertuples()}
    extra = c2.multiselect("Search instruments", sorted(lab), key="ca_any")
    typed = c2.text_input("or type tickers", key="ca_typed")
    options = [lab[x] for x in extra] + [t.strip().upper() for t in typed.split(",") if t.strip()]
    names = {t: pf.lookup_name(t, instruments)[:30] for t in options}

if not options:
    st.info("Choose instruments to analyse.")
    st.stop()
default = [t for t in (focus or {}).get("tickers", []) if t in options] or options[:1]
if focus:
    st.session_state["ca_sel"] = default
sel = st.multiselect("Constituents to analyse (1 = single deep-dive, 2+ = comparison)", options, default=default,
                     format_func=lambda t: f"{names.get(t, t)} ({t})", key="ca_sel")
if not sel:
    st.stop()

tick = list(dict.fromkeys(sel + (options if h is not None else [])))
md = pui.market_data(tick, cfg)
pui.data_quality_box(md)

port_series, s = None, None
if h is not None and h["weight"].sum() > 0:
    w_all = pf.aggregate_by_ticker(h)
    s = pf.portfolio_summary(md, w_all, cfg["conf"], cfg["h"], mc_sims=2000)
    if "error" not in s:
        port_series = s["series"]
    else:
        s = None

# --------------------------------------------------------------------------
if len(sel) == 1:
    t = sel[0]
    if t not in md.returns:
        st.error(f"No price data for {t}.")
        st.stop()
    r = md.returns[t].dropna()
    mu, sd = r.mean() * md.ppy, r.std() * np.sqrt(md.ppy)
    k = st.columns(6)
    k[0].metric("Ann. return", pui.pct(mu))
    k[1].metric("Ann. volatility", pui.pct(sd))
    k[2].metric("Sharpe", pui.num((mu - md.rf_annual) / sd if sd else np.nan))
    k[3].metric("Max drawdown", pui.pct(pf.max_drawdown(r)))
    k[4].metric(f"VaR {cfg['conf']:.0%} {cfg['h']}d", pui.pct(pf.var_parametric(mu, sd, cfg["conf"], cfg["h"])))
    if s is not None and t in s["risk"].index:
        rc = s["risk"].loc[t]
        pui.imetric(k[5], "Share of portfolio risk", pui.pct(rc["% risk"]), f"weight {pui.pct(rc['weight'])}")
    pui.single_asset_tabs(t, md, names.get(t, t), key=f"ca_{t}", port_series=port_series)
    st.stop()

# --------------------------------------------------------------------------
sel_ok = [t for t in sel if t in md.returns]
R = md.returns[sel_ok]
lbl = lambda t: names.get(t, t)[:18]
tabs = st.tabs(["📋 Comparison", "📈 Performance", "🔗 Correlation", "🌪️ Volatility", "β Beta", "🧺 Selection as a portfolio",
                "🔎 Deep-dive one"])

with tabs[0]:
    rows = []
    for t in sel_ok:
        r = R[t].dropna()
        mu, sd = r.mean() * md.ppy, r.std() * np.sqrt(md.ppy)
        dd = pf.downside_deviation(r, md.ppy, md.rf_annual)
        row = {"name": names.get(t, t), "since": r.index.min().date() if len(r) else None,
               "ann. return": mu, "CAGR": pf.cagr(r, md.ppy), "ann. vol": sd,
               "Sharpe": (mu - md.rf_annual) / sd if sd else np.nan, "Sortino": (mu - md.rf_annual) / dd if dd else np.nan,
               "max DD": pf.max_drawdown(r), "skew": r.skew(), "excess kurt.": r.kurt(),
               f"VaR {cfg['conf']:.0%} {cfg['h']}d param": pf.var_parametric(mu, sd, cfg["conf"], cfg["h"]),
               f"VaR hist": pf.var_historical(r, md.ppy, cfg["conf"], cfg["h"])[0]}
        for b in md.bench_returns.columns:
            row[f"β {b}"] = pf.beta_to(r, md.bench_returns[b])[0]
        if port_series is not None:
            row["corr to portfolio"] = pf.beta_to(r, port_series)[1]
            if t in s["risk"].index:
                row["weight"] = s["risk"].loc[t, "weight"]
                row["% of port. risk"] = s["risk"].loc[t, "% risk"]
        rows.append(row)
    ct = pd.DataFrame(rows, index=sel_ok)
    pc = ["ann. return", "CAGR", "ann. vol", "max DD", f"VaR {cfg['conf']:.0%} {cfg['h']}d param", "VaR hist", "weight", "% of port. risk"]
    ctd = pui.as_pct(ct, pc)
    st.dataframe(ctd.round(3), width="stretch", column_config=pui.pct_cols(ctd, pc))
    pts = pd.DataFrame({"vol": ct["ann. vol"], "return": ct["ann. return"]})
    pts.index = [lbl(t) for t in pts.index]
    hl = {"Portfolio": (s["vol"], s["exp_return"])} if s is not None else None
    st.plotly_chart(pui.scatter_risk_return(pts, highlight=hl, h=420), width="stretch")
    pui.formulas("Annualised return", "Annualised volatility", "Sharpe ratio", "Sortino ratio", "Parametric VaR", "Historical VaR")

with tabs[1]:
    P = md.prices_base[sel_ok]
    P = P[P.index >= R.index.min() - pd.Timedelta(days=7)] if len(R) else P
    norm = P.apply(lambda c: c / c.dropna().iloc[0] - 1 if c.notna().any() else c)
    norm.columns = [lbl(t) for t in norm.columns]
    for b in md.bench_returns.columns:
        norm[f"{b} (bench)"] = (1 + md.bench_returns[b].fillna(0)).cumprod().reindex(norm.index).ffill() - 1
    if len(norm.columns) > 8:
        st.caption("Showing the first 8 series; narrow the selection to see the rest.")
    st.plotly_chart(pui.line_chart(norm.iloc[:, :8], f"Cumulative return ({cfg['base']})", h=440), width="stretch")
    dd = pd.DataFrame({lbl(t): pf.drawdown_series(R[t]) for t in sel_ok})
    st.plotly_chart(pui.line_chart(dd.iloc[:, :8], "Drawdown", h=300), width="stretch")

with tabs[2]:
    corr = R.corr(min_periods=12)
    corr.index = corr.columns = [lbl(t) for t in corr.columns]
    st.plotly_chart(pui.corr_heatmap(corr), width="stretch")
    c1, c2, c3 = st.columns(3)
    a = c1.selectbox("Pair: A", sel_ok, format_func=lbl, key="ca_pa")
    b = c2.selectbox("Pair: B", [t for t in sel_ok if t != a], format_func=lbl, key="ca_pb")
    win_def = {"Daily": 63, "Weekly": 26, "Monthly": 12}[cfg["frequency"]]
    win = c3.slider("Window", max(6, win_def // 3), win_def * 4, win_def, key="ca_cw")
    rc = pd.DataFrame({f"{lbl(a)} × {lbl(b)}": R[a].rolling(win).corr(R[b])})
    f = pui.line_chart(rc, "Rolling correlation", pct_axis=False, h=300)
    f.update_yaxes(range=[-1, 1])
    st.plotly_chart(f, width="stretch")
    pui.formulas("Correlation")

with tabs[3]:
    win_def = {"Daily": 63, "Weekly": 26, "Monthly": 12}[cfg["frequency"]]
    win = st.slider("Rolling window (periods)", max(6, win_def // 3), win_def * 4, win_def, key="ca_vw")
    rv = pd.DataFrame({lbl(t): R[t].rolling(win).std() * np.sqrt(md.ppy) for t in sel_ok})
    st.plotly_chart(pui.line_chart(rv.iloc[:, :8], "Rolling annualised volatility", h=380), width="stretch")
    # current vs historical vol range per name
    rng = []
    for t in sel_ok:
        v = (R[t].rolling(win).std() * np.sqrt(md.ppy)).dropna()
        if len(v):
            rng.append({"name": lbl(t), "min": v.min(), "median": v.median(), "max": v.max(), "current": v.iloc[-1],
                        "percentile of current": (v <= v.iloc[-1]).mean()})
    if rng:
        rg = pd.DataFrame(rng)
        fig = go.Figure()
        fig.add_bar(y=rg["name"], x=(rg["max"] - rg["min"]) * 100, base=rg["min"] * 100, orientation="h",
                    marker_color="rgba(57,135,229,0.3)", name="historical range",
                    hovertemplate="%{y}<br>range %{base:.1f}% – %{x:.1f}pp<extra></extra>")
        fig.add_scatter(y=rg["name"], x=rg["median"] * 100, mode="markers", name="median",
                        marker=dict(symbol="line-ns-open", size=16, color=pui.TEXT))
        fig.add_scatter(y=rg["name"], x=rg["current"] * 100, mode="markers", name="current",
                        marker=dict(size=11, color=pui.SERIES[1], line=dict(color="#131722", width=2)))
        fig.update_xaxes(ticksuffix="%", title=f"{win}-period rolling vol")
        fig.update_layout(yaxis=dict(autorange="reversed"))
        st.markdown("**Where is each name's volatility now, versus its own history?**")
        st.plotly_chart(pui._layout(fig, max(280, 34 * len(rg) + 80)), width="stretch")
        rgd = pui.as_pct(rg, ["min", "median", "max", "current", "percentile of current"])
        st.dataframe(rgd.round(2), hide_index=True, width="stretch",
                     column_config=pui.pct_cols(rgd, ["min", "median", "max", "current", "percentile of current"]))
    pui.formulas("Annualised volatility")

with tabs[4]:
    benches = md.bench_returns.copy()
    if port_series is not None:
        benches["Portfolio"] = port_series
    if benches.empty:
        st.info("No benchmarks.")
    else:
        bsel = st.selectbox("Benchmark", list(benches.columns), key="ca_bb")
        win_def = {"Daily": 126, "Weekly": 52, "Monthly": 24}[cfg["frequency"]]
        win = st.slider("Rolling window", max(6, win_def // 4), win_def * 3, win_def, key="ca_bw")
        rb = pd.DataFrame({lbl(t): R[t].rolling(win).cov(benches[bsel]) / benches[bsel].rolling(win).var() for t in sel_ok})
        f = pui.line_chart(rb.iloc[:, :8], f"Rolling beta vs {bsel}", pct_axis=False, h=380)
        f.add_hline(y=1, line_dash="dot", line_color=pui.MUTED)
        st.plotly_chart(f, width="stretch")
        full = pd.DataFrame({b: {lbl(t): pf.beta_to(R[t], benches[b])[0] for t in sel_ok} for b in benches.columns})
        st.dataframe(full.round(3), width="stretch")
    pui.formulas("Beta")

with tabs[5]:
    st.markdown("How do the selected names behave **as a group**? Weights are their current portfolio weights, rescaled "
                "to 100% (edit below).")
    if h is not None:
        w0 = pf.aggregate_by_ticker(h).reindex(sel_ok).fillna(0)
    else:
        w0 = pd.Series(0.0, index=sel_ok)
    if w0.sum() == 0:
        w0[:] = 1
    wdf = pd.DataFrame({"name": [names.get(t, t) for t in sel_ok], "weight %": (w0 / w0.sum() * 100).round(2).values}, index=sel_ok)
    wdf = st.data_editor(wdf, width="stretch", key="ca_subw", disabled=["name"])
    ws = wdf["weight %"].astype(float)
    ss = pf.portfolio_summary(md, ws / ws.sum(), cfg["conf"], cfg["h"], mc_sims=5000)
    if "error" not in ss:
        k = st.columns(6)
        k[0].metric("Volatility", pui.pct(ss["vol"]))
        k[1].metric("Exp. return", pui.pct(ss["exp_return"]))
        k[2].metric("Sharpe", pui.num(ss["sharpe"]))
        k[3].metric(f"VaR {cfg['conf']:.0%} {cfg['h']}d", pui.pct(ss["var_param"]))
        k[4].metric("Avg correlation", pui.num(ss["avg_corr_equal"]))
        k[5].metric("Diversification ratio", pui.num(ss["div_ratio"]))
        st.plotly_chart(pui.bar_weight_vs_risk(ss["risk"], names), width="stretch")
        if s is not None:
            inport = s["risk"].reindex(sel_ok).dropna()
            st.markdown(f"Inside the full portfolio these {len(inport)} names are **{pui.pct(inport['weight'].sum(), 1)} of capital** "
                        f"and **{pui.pct(inport['% risk'].sum(), 1)} of total risk**.")
    pui.formulas("Portfolio variance & volatility", "Risk contribution")

with tabs[6]:
    one = st.selectbox("Instrument", sel_ok, format_func=lambda t: f"{names.get(t, t)} ({t})", key="ca_one")
    pui.single_asset_tabs(one, md, names.get(one, one), key=f"cam_{one}", port_series=port_series)

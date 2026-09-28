import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src import portfolio as pf
from src import portfolio_ui as pui
from src import universe as uni
from src.common import bootstrap

bootstrap("Live Portfolio Risk", "🛡️")
cfg = pui.settings_sidebar()

st.title("🛡️ Live Portfolio Risk — what *is*")
st.caption("Risk of the portfolio you actually hold, today's weights, measured on "
           f"**{cfg['frequency'].lower()} {cfg['base']} returns over {cfg['lookback']}**. Change assumptions in the sidebar.")

name, h = pui.pick("live", "Live portfolio", "pf_live_pick")
if h is None or h.empty:
    st.stop()
_, payload = (None, {}) if name in pui.working()["live"] else pf.load_portfolio("live", name)
value_ccy = payload.get("meta", {}).get("value_ccy", "ZAR") if payload else "ZAR"

hv = h[h["ticker"] != ""]
md = pui.market_data(hv["ticker"].tolist(), cfg)
pui.data_quality_box(md, h)
w = pf.aggregate_by_ticker(hv)
total_value = h["value"].sum(min_count=1)
fx = md.fx_last(value_ccy) if cfg["base"] != "LOCAL" else 1.0
value_base = total_value * fx if total_value == total_value and fx == fx else None
ccy_lbl = cfg["base"] if cfg["base"] != "LOCAL" else value_ccy

s = pf.portfolio_summary(md, w, cfg["conf"], cfg["h"])
if "error" in s:
    st.error(s["error"])
    st.stop()
labels = {r.ticker: (r.name[:28] if r.name else r.ticker) for r in hv.drop_duplicates("ticker").itertuples()}

# --------------------------------------------------------------------------
# Headline KPIs
# --------------------------------------------------------------------------
conf_lbl, hd = f"{cfg['conf']:.0%}", cfg["h"]
k = st.columns(6)
k[0].metric(f"Value ({ccy_lbl})", pui.money_short(value_base, ccy_lbl) if value_base else "—",
            help=f"Sum of holding values ({value_ccy}) × latest {value_ccy}/{ccy_lbl} rate.")
k[1].metric("Volatility (ann.)", pui.pct(s["vol"]), help="σp = √(wᵀΣw), ex-ante with today's weights.")
k[2].metric("Expected return (ann.)", pui.pct(s["exp_return"]), help="wᵀμ from historical mean returns.")
k[3].metric("Sharpe", pui.num(s["sharpe"]), help=f"(μp − rf) / σp with rf = {cfg['rf']:.2%}")
k[4].metric("Sortino", pui.num(s["sortino"]))
k[5].metric("Max drawdown", pui.pct(s["max_dd"]))
k = st.columns(6)
money_var = (lambda v: f" · {pui.money_short(v * value_base, ccy_lbl)} at risk") if value_base else (lambda v: "")
pui.imetric(k[0], f"VaR {conf_lbl} {hd}d (param.)", pui.pct(s["var_param"]), money_var(s["var_param"]).strip(" ·") or None)
pui.imetric(k[1], f"VaR {conf_lbl} {hd}d (hist.)", pui.pct(s["var_hist"]), money_var(s["var_hist"]).strip(" ·") or None)
pui.imetric(k[2], f"CVaR / ES {conf_lbl} (hist.)", pui.pct(s["cvar_hist"]), money_var(s["cvar_hist"]).strip(" ·") or None)
blist = list(s["bench"].items())
for i in range(2):
    if i < len(blist):
        k[3 + i].metric(f"Beta vs {blist[i][0]}", pui.num(blist[i][1]["beta_weighted"]),
                        help=f"Σ wᵢβᵢ. Regression beta of the portfolio series: {blist[i][1]['beta_regression']:.2f}")
pui.imetric(k[5], "Diversification ratio", pui.num(s["div_ratio"]), f"Eff. N {s['eff_n']:.1f}")
st.caption(f"{s['n_assets']} holdings with data · {s['obs']} {cfg['frequency'].lower()} observations "
           f"({s['start']:%Y-%m-%d} → {s['end']:%Y-%m-%d}) · money amounts in {ccy_lbl}.")
if s["dropped"]:
    st.warning(f"Excluded (no data): {', '.join(s['dropped'])}")

tabs = st.tabs(["🎯 Risk contribution", "β Beta & benchmarks", "🔗 Correlation", "📉 VaR & distribution",
                "📈 Performance & drawdown", "⏱️ Rolling risk", "🗂️ Accounts & categories", "📋 Holdings detail"])

# --------------------------------------------------------------------------
with tabs[0]:
    rc = s["risk"].copy()
    c1, c2 = st.columns([1.5, 1])
    with c1:
        st.markdown("**Weight vs share of portfolio risk** (top 25 by risk)")
        st.plotly_chart(pui.bar_weight_vs_risk(rc, labels), width="stretch")
    with c2:
        top = rc.sort_values("% risk", ascending=False)
        conc = top["% risk"].head(5).sum()
        pui.imetric(st, "Top-5 holdings' share of risk", pui.pct(conc, 1), f"{pui.pct(top['weight'].head(5).sum(), 1)} of capital")
        ratio = (rc["% risk"] / rc["weight"].replace(0, np.nan)).dropna().sort_values(ascending=False)
        st.markdown("**Risk-to-weight ratio** (>1 = contributes more risk than capital)")
        rr = pd.DataFrame({"holding": [labels.get(t, t) for t in ratio.index], "risk ÷ weight": ratio.values.round(2)})
        st.dataframe(rr, hide_index=True, width="stretch", height=420)
    tbl = rc.copy()
    tbl.insert(0, "name", [labels.get(t, t) for t in tbl.index])
    tbl["ann. vol"] = np.sqrt(np.diag(s["cov"].loc[tbl.index, tbl.index]))
    tbl = pui.as_pct(tbl.sort_values("% risk", ascending=False), ["weight", "MCTR", "CTR", "% risk", "ann. vol"])
    st.dataframe(tbl, width="stretch", column_config=pui.pct_cols(tbl, ["weight", "MCTR", "CTR", "% risk", "ann. vol"]))
    pui.formulas("Covariance matrix", "Portfolio variance & volatility", "Risk contribution", "Diversification")

# --------------------------------------------------------------------------
with tabs[1]:
    rows = []
    for label, b in s["bench"].items():
        rows.append({"Benchmark": label, "Beta (Σwβ)": b["beta_weighted"], "Beta (regression)": b["beta_regression"],
                     "Correlation": b["correlation"], "R²": b["r2"], "Tracking error": b["tracking_error"],
                     "Info ratio": b["info_ratio"], "Jensen's α": b["alpha_jensen"], "Treynor": b["treynor"],
                     "Up capture": b["up_capture"], "Down capture": b["down_capture"],
                     "Bench vol": b["bench_vol"], "Bench return": b["bench_return"]})
    bt = pd.DataFrame(rows)
    bt = pui.as_pct(bt, ["Tracking error", "Jensen's α", "Bench vol", "Bench return"])
    st.dataframe(bt.round(3), hide_index=True, width="stretch",
                 column_config=pui.pct_cols(bt, ["Tracking error", "Jensen's α", "Bench vol", "Bench return"]))
    if s["bench"]:
        bsel = st.selectbox("Constituent betas vs", list(s["bench"].keys()), key="live_beta_b")
        betas = s["bench"][bsel]["betas_i"]
        bdf = pd.DataFrame({"beta": betas, "weight": s["weights"]}).loc[lambda d: d["weight"] > 0]
        bdf["weighted beta (w·β)"] = bdf["beta"] * bdf["weight"]
        nb = st.slider("Holdings to chart (largest by weight)", 5, max(5, len(bdf)), min(30, len(bdf)), key="live_beta_n")
        bdf = bdf.nlargest(nb, "weight").sort_values("beta", ascending=False)
        bdf.index = [labels.get(t, t) for t in bdf.index]
        c1, c2 = st.columns([1.4, 1])
        fig = go.Figure(go.Bar(x=bdf["beta"], y=bdf.index, orientation="h", marker_color=pui.SERIES[0],
                               customdata=bdf["weight"] * 100,
                               hovertemplate="%{y}<br>β %{x:.2f}<br>weight %{customdata:.2f}%<extra></extra>"))
        fig.add_vline(x=1, line_dash="dot", line_color=pui.MUTED)
        fig.update_layout(yaxis=dict(autorange="reversed"), xaxis_title=f"Beta vs {bsel}")
        c1.plotly_chart(pui._layout(fig, max(320, 20 * len(bdf) + 80), showlegend=False), width="stretch")
        c2.markdown("**Largest contributors to portfolio beta**")
        show = bdf.sort_values("weighted beta (w·β)", ascending=False)
        c2.dataframe(show.assign(weight=show["weight"] * 100).round(3), width="stretch", height=500,
                     column_config={"weight": st.column_config.NumberColumn("weight", format="%.2f%%")})
        port_b = s["bench"][bsel]["beta_weighted"]
        st.markdown("**Beta hedge calculator**")
        h1, h2, h3 = st.columns(3)
        tgt = h1.number_input("Target beta", 0.0, 3.0, float(round(max(0.0, port_b - 0.1), 2)), 0.05, key="live_tb")
        hb = h2.number_input("Hedge instrument beta", 0.1, 3.0, 1.0, 0.05, key="live_hb",
                             help="e.g. 1.0 for a Top 40 future / index ETF short")
        if value_base:
            notional = pf.beta_hedge(value_base, port_b, tgt, hb)
            h3.metric("Notional to short (+) / buy (−)", pui.money(notional, ccy_lbl))
    pui.formulas("Beta", "Tracking error & information ratio", "Target volatility & beta hedge")

# --------------------------------------------------------------------------
with tabs[2]:
    R = md.returns[[t for t in s["weights"].index if s["weights"][t] > 0 and t != pf.CASH_TICKER]]
    order = s["weights"].reindex(R.columns).sort_values(ascending=False).index
    topn = st.slider("Holdings to show (largest by weight)", 5, max(5, len(order)), min(25, len(order)), key="live_corr_n")
    corr = R[order[:topn]].corr(min_periods=12)
    corr.index = corr.columns = [labels.get(t, t)[:18] for t in corr.columns]
    st.plotly_chart(pui.corr_heatmap(corr), width="stretch")
    c1, c2 = st.columns(2)
    c1.metric("Average pairwise correlation (equal-weighted)", pui.num(s["avg_corr_equal"], 3),
              help="Same as the TFSA sheet: average of all pairs, ignores weights.")
    c2.metric("Weight-implied average correlation", pui.num(s["avg_corr_weighted"], 3))
    # most / least correlated pairs
    cc = R[order[:topn]].corr(min_periods=12)
    iu = np.triu_indices_from(cc, 1)
    pairs = pd.DataFrame({"A": [labels.get(cc.index[i], cc.index[i]) for i in iu[0]],
                          "B": [labels.get(cc.columns[j], cc.columns[j]) for j in iu[1]], "ρ": cc.values[iu]}).dropna()
    p1, p2 = st.columns(2)
    p1.markdown("**Most correlated pairs** (little diversification between them)")
    p1.dataframe(pairs.nlargest(10, "ρ").round(3), hide_index=True, width="stretch")
    p2.markdown("**Least correlated pairs** (best diversifiers)")
    p2.dataframe(pairs.nsmallest(10, "ρ").round(3), hide_index=True, width="stretch")
    pui.formulas("Correlation")

# --------------------------------------------------------------------------
with tabs[3]:
    comp = pd.DataFrame([
        {"Method": "Parametric (normal)", "VaR": s["var_param"], "CVaR / ES": s["cvar_param"]},
        {"Method": "Historical", "VaR": s["var_hist"], "CVaR / ES": s["cvar_hist"]},
        {"Method": "Cornish-Fisher (skew/kurtosis adj.)", "VaR": s["var_cf"], "CVaR / ES": np.nan},
        {"Method": "Monte Carlo (20k scenarios)", "VaR": s["var_mc"], "CVaR / ES": s["cvar_mc"]},
    ])
    if value_base:
        comp[f"VaR ({ccy_lbl})"] = comp["VaR"] * value_base
        comp[f"CVaR ({ccy_lbl})"] = comp["CVaR / ES"] * value_base
    c1, c2 = st.columns([1, 1.4])
    with c1:
        st.markdown(f"**{conf_lbl} confidence, {hd}-trading-day horizon**")
        disp = pui.as_pct(comp, ["VaR", "CVaR / ES"])
        cc_ = pui.pct_cols(disp, ["VaR", "CVaR / ES"])
        cc_.update({c: st.column_config.NumberColumn(c, format="%,.0f") for c in disp.columns if "(" in c and ccy_lbl in c})
        st.dataframe(disp, hide_index=True, width="stretch", column_config=cc_)
        st.metric("Skewness of portfolio returns", pui.num(s["skew"]))
        st.metric("Excess kurtosis", pui.num(s["excess_kurt"]),
                  help=">0 = fatter tails than a normal distribution; historical / CF VaR will exceed parametric.")
        st.caption("Read it as: *with 95% confidence, the portfolio should not lose more than VaR over the next "
                   f"{hd} trading days; when it does, the average loss is the CVaR.*")
    with c2:
        port = s["series"]
        n = max(1, int(round(pf.horizon_periods(hd, md.ppy))))
        hret = (np.exp(np.log1p(port).rolling(n).sum()) - 1).dropna() if n > 1 else port
        st.plotly_chart(pui.var_hist_chart(hret, {"Param": s["var_param"], "Hist": s["var_hist"], "CF": s["var_cf"]},
                                           f"Historical {n}-period portfolio returns"), width="stretch")
        st.plotly_chart(pui.var_hist_chart(s["mc_dist"], {"MC VaR": s["var_mc"], "MC ES": s["cvar_mc"]},
                                           f"Monte Carlo {hd}-day portfolio returns"), width="stretch")
    # VaR backtest: how often did actual losses exceed the parametric one-period VaR?
    one = pf.var_parametric(s["exp_return"], s["vol"], cfg["conf"], int(round(252 / md.ppy)))
    breaches = (port < -one).mean()
    st.markdown(f"**Backtest:** one-period parametric VaR = {pui.pct(one)}; actual breach rate "
                f"**{pui.pct(breaches, 1)}** vs expected {pui.pct(1 - cfg['conf'], 1)} "
                f"({'fat tails -- parametric understates risk' if breaches > 1.25 * (1 - cfg['conf']) else 'consistent'}).")
    pui.formulas("Parametric VaR", "Historical VaR", "Expected Shortfall (CVaR)", "Cornish-Fisher VaR", "Monte Carlo VaR")

# --------------------------------------------------------------------------
with tabs[4]:
    port = s["series"]
    cum = pd.DataFrame({"Portfolio": (1 + port).cumprod() - 1})
    for b in md.bench_returns.columns:
        cum[b] = (1 + md.bench_returns[b].reindex(port.index).fillna(0)).cumprod() - 1
    st.plotly_chart(pui.line_chart(cum, f"Cumulative return ({cfg['base']})"), width="stretch")
    st.caption("Constant-weight back-test: today's weights held (rebalanced each period) over the lookback. "
               "This is how the *current* mix would have behaved -- not your actual historical account performance.")
    st.plotly_chart(pui.drawdown_chart(pf.drawdown_series(port)), width="stretch")
    m = st.columns(5)
    m[0].metric("CAGR", pui.pct(s["cagr"]))
    m[1].metric("Realised vol", pui.pct(s["realised_vol"]))
    m[2].metric("Downside deviation", pui.pct(s["downside_dev"]))
    m[3].metric("Calmar", pui.num(s["calmar"]))
    m[4].metric("Worst period", pui.pct(port.min()))
    # calendar-year returns
    yr = (1 + port).groupby(port.index.year).prod() - 1
    ydf = pd.DataFrame({"Portfolio": yr})
    for b in md.bench_returns.columns:
        br = md.bench_returns[b].reindex(port.index)
        ydf[b] = (1 + br).groupby(br.index.year).prod() - 1
    ydf = (ydf * 100).round(2)
    ydf.index.name = "Year"
    st.markdown("**Calendar-year returns (%)**")
    st.dataframe(ydf.T, width="stretch")
    pui.formulas("Annualised return", "Maximum drawdown", "Sortino ratio")

# --------------------------------------------------------------------------
with tabs[5]:
    win_def = {"Daily": 63, "Weekly": 26, "Monthly": 12}[cfg["frequency"]]
    win = st.slider("Rolling window (periods)", max(6, win_def // 3), win_def * 4, win_def, key="live_roll")
    rs = pf.rolling_portfolio_stats(s["series"], md.bench_returns, win, md.ppy)
    st.plotly_chart(pui.line_chart(rs[["rolling vol"]], "Rolling annualised volatility", h=300), width="stretch")
    bcols = [c for c in rs.columns if c.startswith("beta")]
    if bcols:
        f = pui.line_chart(rs[bcols], "Rolling beta", pct_axis=False, h=300)
        f.add_hline(y=1, line_dash="dot", line_color=pui.MUTED)
        st.plotly_chart(f, width="stretch")
        f = pui.line_chart(rs[[c for c in rs.columns if c.startswith("corr")]], "Rolling correlation", pct_axis=False, h=300)
        f.update_yaxes(range=[-1, 1])
        st.plotly_chart(f, width="stretch")

# --------------------------------------------------------------------------
with tabs[6]:
    by = st.radio("Group by", ["account", "category"], horizontal=True, key="live_grp")
    hh = hv.copy()
    if by == "category":
        hh["category"] = hh["category"].str.split(" - ").str[0].str.strip()
    g = pf.group_rollup(hh, md, by, cfg["conf"], cfg["h"])
    if g.empty:
        st.info("No groups.")
    else:
        pcols = ["weight", "% of total risk", "stand-alone vol", "exp return", "max DD", "VaR (param)"]
        gd = pui.as_pct(g, pcols)
        st.dataframe(gd.round(3), hide_index=True, width="stretch", column_config=pui.pct_cols(gd, pcols))
        fig = go.Figure()
        fig.add_bar(x=g[by], y=g["weight"] * 100, name="Weight", marker_color=pui.SERIES[0])
        fig.add_bar(x=g[by], y=g["% of total risk"] * 100, name="% of total risk", marker_color=pui.SERIES[1])
        fig.update_layout(barmode="group", yaxis_title="%")
        st.plotly_chart(pui._layout(fig, 340), width="stretch")
        st.caption("Stand-alone metrics treat each group as its own portfolio. '% of total risk' is its contribution "
                   "to the whole portfolio's volatility (sums to 100%).")

# --------------------------------------------------------------------------
with tabs[7]:
    at = pf.asset_table(md, w, cfg["conf"], cfg["h"])
    at.insert(0, "name", [labels.get(t, t) for t in at.index])
    acc = hv.groupby("ticker")["account"].agg(lambda x: ", ".join(sorted(set(a for a in x if a))))
    at.insert(1, "account", acc.reindex(at.index).fillna(""))
    pc = ["weight", "ann_return", "cagr", "ann_vol", "max_dd", "var_param", "var_hist", "MCTR", "CTR", "pct_risk"]
    at = pui.as_pct(at.sort_values("weight", ascending=False), pc)
    st.dataframe(at.round(3), width="stretch", height=600, column_config=pui.pct_cols(at, pc))
    st.download_button("⬇️ Download table (CSV)", at.to_csv().encode(), f"{name}_risk_{pd.Timestamp.today():%Y%m%d}.csv")
    focus = st.multiselect("Drill into constituents", list(at.index), format_func=lambda t: labels.get(t, t), key="live_focus")
    if focus and st.button("Open in Constituent Analysis →"):
        st.session_state["pf_focus"] = {"kind": "live", "name": name, "tickers": focus}
        st.switch_page("pages/24_Constituent_Analysis.py")
    pui.formulas("Annualised return", "Annualised volatility", "Sharpe ratio", "Sortino ratio", "Beta")
